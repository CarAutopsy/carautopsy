"""Branch-scoped pilot staging runner.

Reads approved candidate JSON, validates every record against the price-tier
contract, and writes only into a branch-scoped ``staging/`` directory. It never
writes to ``catalog/variants/`` and never creates records for a failed batch.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import price_tier

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "catalog" / "variants"
STAGING_ROOT = ROOT / "staging"


class StagingError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def safe_staging_dir(path: Path, root: Path = ROOT) -> Path:
    """Require a branch-scoped path under staging/, never catalog/variants/."""
    resolved = path.resolve()
    catalog = (root / "catalog" / "variants").resolve()
    staging = (root / "staging").resolve()
    if resolved == catalog or catalog in resolved.parents:
        raise StagingError("UNSAFE_OUTPUT_PATH")
    if resolved == staging or staging not in resolved.parents:
        raise StagingError("UNSAFE_OUTPUT_PATH")
    return resolved


def safe_report_path(path: Path, root: Path = ROOT) -> Path:
    resolved = path.resolve()
    catalog = (root / "catalog" / "variants").resolve()
    if resolved == catalog or catalog in resolved.parents:
        raise StagingError("UNSAFE_REPORT_PATH")
    return resolved


def load_candidates(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StagingError("INVALID_CANDIDATE_FILE") from exc
    if isinstance(payload, dict):
        payload = payload.get("candidates")
    if not isinstance(payload, list):
        raise StagingError("INVALID_CANDIDATE_FILE")
    if not all(isinstance(item, dict) for item in payload):
        raise StagingError("INVALID_CANDIDATE_FILE")
    return payload


def _candidate_key(record: dict[str, Any]) -> tuple[Any, ...]:
    brand, model, variant, year = price_tier.candidate_identity(record)
    return (brand, model, variant, year, price_tier.field(record, "price_source_url"))


def validate_candidates(candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return validation outcome with duplicates/conflicts separated out."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    duplicates: list[str] = []
    conflicts: list[str] = []
    seen: dict[tuple[Any, ...], float | None] = {}

    for record in candidates:
        label = f"{record.get('brand', '?')}/{record.get('model', '?')}"
        errors: list[str] = []
        if not record.get("brand") or not record.get("model"):
            errors.append("brand and model are required")
        errors.extend(price_tier.validate_price_fields(record))
        key = _candidate_key(record)
        price = price_tier.field(record, "price_value")
        if key in seen:
            if seen[key] is not None and price is not None and seen[key] != price:
                conflicts.append(label)
            else:
                duplicates.append(label)
            continue
        if errors:
            rejected.append({"candidate": label, "errors": errors})
            continue
        seen[key] = price
        accepted.append(record)

    return {
        "accepted": accepted,
        "rejected": rejected,
        "duplicates": duplicates,
        "conflicts": conflicts,
    }


def build_staging_record(record: dict[str, Any], source_file: str) -> dict[str, Any]:
    """Normalize provenance names and mark the result as staging-only."""
    staged = dict(record)
    staged["price_value"] = price_tier.field(record, "price_value")
    staged["price_source_url"] = price_tier.field(record, "price_source_url")
    staged["price_source_date"] = price_tier.field(record, "price_source_date")
    staged["price_confidence"] = price_tier.field(record, "price_confidence")
    staged["price_adjustment_method"] = price_tier.field(record, "price_adjustment_method")
    staged["vat_basis"] = record.get("vat_basis")
    staged["review_required"] = record.get("review_required") is True
    staged["catalog_written"] = False
    staged["staging_only"] = True
    staged["staging_report_source"] = source_file
    staged["provider_calls"] = 0
    staged["staged_at"] = datetime.now(timezone.utc).isoformat()
    return staged


def _filename(record: dict[str, Any], index: int) -> str:
    raw = "-".join(str(part or "") for part in price_tier.candidate_identity(record))
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-").lower() or "candidate"
    return f"{index:03d}-{slug}.json"


def run(candidates_path: Path, *, output_dir: Path | None = None,
        report_path: Path | None = None, dry_run: bool = False,
        root: Path = ROOT) -> dict[str, Any]:
    candidates = load_candidates(candidates_path)
    outcome = validate_candidates(candidates)
    accepted = outcome["accepted"]
    blocked = bool(outcome["rejected"] or outcome["conflicts"])
    written: list[str] = []

    destination: Path | None = None
    if not dry_run and not blocked and output_dir is not None:
        destination = safe_staging_dir(output_dir, root)
        destination.mkdir(parents=True, exist_ok=True)
        for index, record in enumerate(accepted, 1):
            target = destination / _filename(record, index)
            target.write_text(
                json.dumps(build_staging_record(record, candidates_path.name),
                           indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            written.append(target.name)

    report = {
        "schema_version": 1,
        "status": "REJECTED" if blocked else ("DRY_RUN" if dry_run else "STAGED"),
        "source_candidate_file": str(candidates_path),
        "dry_run": dry_run,
        "output_dir": str(destination) if destination else None,
        "accepted": len(accepted),
        "rejected": len(outcome["rejected"]),
        "duplicates": len(outcome["duplicates"]),
        "conflicts": len(outcome["conflicts"]),
        "errors": len(outcome["rejected"]),
        "written": len(written),
        "written_files": written,
        "catalog_variants_written": 0,
        "provider_calls": 0,
        "rejection_details": outcome["rejected"],
        "duplicate_candidates": outcome["duplicates"],
        "conflict_candidates": outcome["conflicts"],
    }
    if report_path is not None:
        safe_report_path(report_path, root).write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.dry_run and args.output_dir is None:
        parser.error("--output-dir is required unless --dry-run is set")
    try:
        report = run(args.candidates, output_dir=args.output_dir,
                     report_path=args.report, dry_run=args.dry_run)
    except StagingError as exc:
        print(f"STAGING_BLOCKED: {exc.code}", file=sys.stderr)
        return 3
    print(json.dumps({k: v for k, v in report.items() if k not in ("written_files", "rejection_details")},
                     indent=2, sort_keys=True))
    return 0 if report["status"] != "REJECTED" else 4


if __name__ == "__main__":
    raise SystemExit(main())
