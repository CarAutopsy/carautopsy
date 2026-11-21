"""Offline bulk catalog ingestion over committed EEA evidence.

Reads only local, already-committed source configuration and evidence. Never
performs network access, never writes catalog/variants/, and requires an
explicit branch-scoped staging directory for any file output.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catalog_quality import detect_duplicates, normalize_identity
from jsonschema import Draft7Validator
from report_research_coverage import (
    KEY_FIELDS,
    PRICE_ROW_FIELDS,
    enrich_record,
    identity_row_problems,
    key_fields,
    load_evidence,
    missing_fields,
)
from validate_catalog import DEFAULT_SCHEMA
from validate_eea_with_adapters import (
    evaluate_statutory,
    load_statutory_rules,
    map_row,
    read_rows,
)
from validate_tco_readiness import validate_variant_readiness

SCHEMA_VERSION = 1
MAX_DRY_RUN_RECORDS = 200
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_GATE = 3
EXIT_UNSAFE_PATH = 4
EXIT_READ = 5
CONFIG_FIELDS = (
    "id", "source_name", "source_url", "license", "extraction_date",
    "dataset_year", "sample", "identity_map", "price_evidence",
    "statutory_rules", "selection_doc",
)
CATALOG_DIR = ROOT / "catalog" / "variants"
STAGING_ROOT = ROOT / "staging"


class IngestError(RuntimeError):
    """Actionable failure with a process exit code."""

    def __init__(self, message: str, code: int = EXIT_GATE) -> None:
        super().__init__(message)
        self.code = code


def check_source_gate(root: Path, selection_doc: str) -> None:
    """Fail closed unless the source-selection doc names a permitted source."""
    path = root / selection_doc
    if not path.is_file():
        raise IngestError(f"source selection document missing: {selection_doc}", EXIT_GATE)
    text = path.read_text(encoding="utf-8")
    if "EEA type-approval CO2 microdata" not in text or "CC BY 4.0" not in text:
        raise IngestError(
            f"source selection document does not identify a permitted source: {selection_doc}",
            EXIT_GATE,
        )


def load_source_config(path: Path, root: Path) -> dict[str, Any]:
    """Load and validate a committed source configuration."""
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise IngestError(f"source config must live inside the repository: {path}", EXIT_USAGE)
    if not resolved.is_file():
        raise IngestError(f"source config not found: {path}", EXIT_USAGE)
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise IngestError("source config must be a version 1 JSON object", EXIT_USAGE)
    for field in CONFIG_FIELDS:
        if not str(data.get(field) or "").strip():
            raise IngestError(f"source config missing required field: {field}", EXIT_USAGE)
    check_source_gate(root, str(data["selection_doc"]))
    for field in ("sample", "identity_map", "price_evidence", "statutory_rules", "selection_doc"):
        candidate = (root / str(data[field])).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise IngestError(f"source config path escapes repository: {field}", EXIT_USAGE)
        if not candidate.is_file():
            raise IngestError(f"source config references a missing file: {field} -> {data[field]}", EXIT_USAGE)
    if data.get("dataset_year") not in (2017, 2018, 2019):
        raise IngestError("dataset_year must be one of 2017, 2018, 2019", EXIT_USAGE)
    return data


def safe_output_dir(path: Path, root: Path) -> Path:
    """Require a branch-scoped staging directory, never catalog/variants."""
    resolved = path.resolve()
    staging = (root / "staging").resolve()
    if resolved == CATALOG_DIR.resolve() or resolved.is_relative_to(CATALOG_DIR.resolve()):
        raise IngestError("output directory must not be catalog/variants", EXIT_UNSAFE_PATH)
    if not resolved.is_relative_to(staging) or resolved == staging:
        raise IngestError(
            "output directory must be a branch-scoped path under staging/, e.g. staging/catalog-batch-001",
            EXIT_UNSAFE_PATH,
        )
    return resolved


def safe_report_path(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if resolved == CATALOG_DIR.resolve() or resolved.is_relative_to(CATALOG_DIR.resolve()):
        raise IngestError("report must not be written into catalog/variants", EXIT_UNSAFE_PATH)
    return resolved


def resolve_identity(
    record: dict[str, Any],
    identity_row: dict[str, Any] | None,
) -> tuple[dict[str, str | int | None], list[str]]:
    """Identity-resolution hook using only documented evidence.

    Returns the resolved identity fields and any fields that could not be
    evidenced. Missing optional fields stay null rather than being invented.
    """
    identity = record.get("identity") or {}
    source = record.get("source_fields") or {}
    registration = record.get("registration", {}).get("first_registration_date", "")
    year = int(str(registration)[:4]) if str(registration)[:4].isdigit() else None
    resolved: dict[str, str | int | None] = {
        "make": identity_row.get("consumer_make") if identity_row else None,
        "model": identity_row.get("consumer_model") if identity_row else None,
        "trim": (identity_row or {}).get("trim") or None,
        "generation": (identity_row or {}).get("generation") or None,
        "model_year": year,
        "body_style": identity.get("body_style") or None,
        "powertrain": source.get("powertrain") or identity.get("powertrain") or None,
    }
    missing = [field for field, value in resolved.items() if value in (None, "")]
    for field in ("trim", "generation", "body_style"):
        if field in missing:
            missing.remove(field)
    return resolved, missing


def build_staging_record(
    enriched: dict[str, Any],
    config: dict[str, Any],
    identity_row: dict[str, Any],
    price_row: dict[str, Any],
) -> dict[str, Any]:
    """Return a catalog-shaped record with full provenance (no mutation)."""
    record = json.loads(json.dumps(enriched))
    # The EEA approval code is the stable variant identity; keep it as the
    # slug so distinct variants do not collapse onto the consumer model name.
    raw_variant = (record.get("source_fields") or {}).get("variant")
    if raw_variant:
        record["identity"]["variant_slug"] = raw_variant
    resolved_identity, missing = resolve_identity(record, identity_row)
    record["resolved_identity"] = {
        **resolved_identity,
        "source_url": identity_row["source_url"],
        "license": identity_row["license"],
        "retrieved_at": identity_row["retrieved_at"],
        "reviewed_by": identity_row["reviewed_by"],
        "confidence": identity_row.get("confidence"),
        "cross_checks": identity_row.get("cross_checks", []),
        "unverified_fields": missing,
    }
    record["price_verification"] = {
        "purchase_price_excl_vat_eur": price_row["purchase_price_excl_vat_eur"],
        "price_date": price_row["price_date"],
        "price_date_precision": price_row.get("price_date_precision", "snapshot"),
        "currency": price_row["currency"],
        "market": price_row["market"],
        "source_url": price_row["source_url"],
        "license": price_row["license"],
        "retrieved_at": price_row["retrieved_at"],
        "price_precision": price_row.get("price_precision", "variant_level"),
        "confidence": price_row.get("confidence"),
        "tco_ready": bool(price_row.get("tco_ready", True)),
        "catalog_eligible": bool(price_row.get("catalog_eligible", True)),
        "price_match": (price_row.get("price") or {}).get("match", {}),
    }
    record["identity_quality"] = "identity_resolved"
    record["tco_ready"] = bool(price_row.get("tco_ready", True))
    record["catalog_eligible"] = bool(price_row.get("catalog_eligible", True))
    record["ingestion"] = {
        "source_id": config["id"],
        "source_name": config["source_name"],
        "source_url": config["source_url"],
        "license": config["license"],
        "extraction_date": config["extraction_date"],
        "catalog_written": False,
    }
    record["catalog_written"] = False
    record.pop("requires_owner_approval", None)
    return record


def existing_catalog_records(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Read existing catalog records read-only for collision detection."""
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / "catalog" / "variants").glob("*.json")):
        try:
            records.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return records


def run_ingest(
    *,
    root: Path,
    config: dict[str, Any],
    limit: int,
    batch_size: int,
    dry_run: bool,
    output_dir: Path | None,
    report_path: Path,
) -> dict[str, Any]:
    """Execute one ingestion pass and return a machine-readable report."""
    sample_path = root / str(config["sample"])
    try:
        rows = read_rows(sample_path)
    except (OSError, ValueError) as exc:
        raise IngestError(f"cannot read bulk source sample: {exc}", EXIT_READ) from exc
    rows = rows[:limit]
    identities, _ = load_evidence(root / str(config["identity_map"]))
    prices, _ = load_evidence(root / str(config["price_evidence"]))
    rules = load_statutory_rules(root / str(config["statutory_rules"]))
    schema = json.loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)

    staged: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    mapped = 0

    for row in rows:
        raw = map_row(row, int(config["dataset_year"]), None)
        variant_id = str(raw.get("variant_id") or "unknown")
        key = "|".join(str(key_fields(raw)[field]) for field in KEY_FIELDS)
        identity_row = identities.get(key)
        price_row = prices.get(key)
        reasons: list[str] = []
        if identity_row is None:
            reasons.append("identity_evidence_missing")
        elif identity_row_problems(identity_row):
            reasons.append("identity_evidence_incomplete")
        if price_row is None:
            reasons.append("price_evidence_missing")
        elif missing_fields(price_row, PRICE_ROW_FIELDS):
            reasons.append("price_evidence_incomplete")
        if reasons:
            rejections.append({"variant_id": variant_id, "reasons": reasons})
            continue
        enriched = enrich_record(raw, identity_row, price_row)
        registered = date.fromisoformat(enriched["registration"]["first_registration_date"])
        statutory = evaluate_statutory(enriched, rules, registered)
        if not statutory["verified"] or statutory["findings"]:
            rejections.append({"variant_id": variant_id, "reasons": ["statutory_unverified"]})
            continue
        readiness = validate_variant_readiness(enriched, statutory["taxes"])
        if readiness:
            rejections.append({"variant_id": variant_id, "reasons": ["readiness_failed", *readiness]})
            continue
        schema_errors = [error.message for error in validator.iter_errors(enriched)]
        if schema_errors:
            rejections.append({"variant_id": variant_id, "reasons": ["schema_invalid", *schema_errors[:3]]})
            continue
        mapped += 1
        record = build_staging_record(enriched, config, identity_row, price_row)
        record["statutory"] = statutory
        staged.append(record)

    # Duplicate/conflict detection across the staged batch and the existing catalog.
    all_records = existing_catalog_records(root) + [(Path(v["variant_id"]), v) for v in staged]
    identities_by_id = {
        str(record.get("variant_id") or path.stem): normalize_identity(record, str(record.get("variant_id") or path.stem))
        for path, record in all_records
    }
    findings = detect_duplicates(all_records, identities_by_id)
    conflicts = [item for item in findings if item["category"] == "CONFLICTING_SPECIFICATION"]
    conflict_ids = {item["record_id"] for item in conflicts}
    # Keep the first record for each identity; later members of a duplicate
    # group are dropped rather than writing conflicting catalog entries.
    seen_ids = {str(record.get("variant_id") or path.stem) for path, record in existing_catalog_records(root)}
    seen_keys = {
        identities_by_id[variant_id]["canonical_key"] for variant_id in seen_ids
        if variant_id in identities_by_id
    }
    deduplicated: list[dict[str, Any]] = []
    duplicates_dropped = 0
    for record in sorted(staged, key=lambda item: str(item["variant_id"])):
        variant_id = str(record["variant_id"])
        canonical = identities_by_id[variant_id]["canonical_key"]
        if variant_id in seen_ids or canonical in seen_keys or variant_id in conflict_ids:
            duplicates_dropped += 1
            continue
        seen_ids.add(variant_id)
        seen_keys.add(canonical)
        deduplicated.append(record)
    staged = deduplicated

    written: list[str] = []
    if not dry_run and output_dir is not None:
        destination = safe_output_dir(output_dir, root)
        destination.mkdir(parents=True, exist_ok=True)
        for record in staged[:batch_size]:
            path = destination / f"{record['variant_id']}.json"
            record = dict(record)
            record["catalog_written"] = False  # staging only, never the live catalog
            record["ingestion"]["catalog_written"] = False
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written.append(record["variant_id"])

    report = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "id": config["id"], "source_name": config["source_name"],
            "source_url": config["source_url"], "license": config["license"],
            "extraction_date": config["extraction_date"],
            "dataset_year": config["dataset_year"],
        },
        "dry_run": dry_run,
        "limit": limit,
        "batch_size": batch_size,
        "counts": {
            "read": len(rows),
            "mapped": mapped,
            "rejected": len(rejections),
            "duplicates": duplicates_dropped,
            "conflicts": len(conflicts),
            "written": len(written),
        },
        "rejections": rejections,
        "duplicate_findings": [item for item in findings if item["category"] != "CONFLICTING_SPECIFICATION"],
        "conflict_findings": conflicts,
        "written_variant_ids": written,
        "output_dir": str(output_dir) if output_dir else None,
        "catalog_variants_written": 0,
        "gates": {
            "source_selection_doc": config["selection_doc"],
            "network_access": False,
            "live_catalog_write": False,
        },
    }
    safe_report_path(report_path, root).parent.mkdir(parents=True, exist_ok=True)
    safe_report_path(report_path, root).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="committed bulk source config JSON")
    parser.add_argument("--limit", type=int, default=200, help="maximum source rows to read")
    parser.add_argument("--dry-run", action="store_true", help="process at most 200 records; write no staging files")
    parser.add_argument("--batch-size", type=int, default=50, help="maximum records written per invocation")
    parser.add_argument("--output-dir", type=Path, help="branch-scoped staging directory")
    parser.add_argument("--report", type=Path, required=True, help="machine-readable report path")
    args = parser.parse_args(argv)

    try:
        if args.limit < 1 or args.batch_size < 1:
            raise IngestError("--limit and --batch-size must be positive integers", EXIT_USAGE)
        if not args.dry_run and args.output_dir is None:
            raise IngestError("--output-dir is required unless --dry-run is used", EXIT_USAGE)
        limit = min(args.limit, MAX_DRY_RUN_RECORDS) if args.dry_run else args.limit
        config = load_source_config(Path(args.source), ROOT)
        report = run_ingest(
            root=ROOT, config=config, limit=limit, batch_size=args.batch_size,
            dry_run=args.dry_run,
            output_dir=(ROOT / args.output_dir).resolve() if args.output_dir else None,
            report_path=args.report.resolve(),
        )
    except IngestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_READ

    counts = report["counts"]
    print(
        f"source={report['source']['id']} dry_run={report['dry_run']} "
        f"read={counts['read']} mapped={counts['mapped']} rejected={counts['rejected']} "
        f"duplicates={counts['duplicates']} conflicts={counts['conflicts']} "
        f"written={counts['written']} report={args.report}"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
