"""Offline, deterministic evidence-sprint pipeline for the Austrian pilot.

Reads committed gap-candidate research and a committed wave/gap-class assignment
table, validates both, and emits a structured sprint artifact under docs/. No
network, provider, secret, staging or catalog access is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = ROOT / "docs/research/pilot-gap-price-candidates.json"
DEFAULT_ASSIGNMENTS = ROOT / "docs/research/evidence-sprint-002-assignments.json"

GAP_CLASSES = frozenset({
    "needs_austrian_official_price",
    "needs_dated_austrian_dealer_price",
    "needs_cross_market_evidence",
    "needs_owner_decision",
    "needs_specification_completion",
    "not_offered_in_austria",
})
WAVES = frozenset({1, 2, 3})
REQUIRED_FIELDS = (
    "brand", "model", "tier", "wave", "gap_class", "required_evidence",
    "best_source_type", "next_action", "next_evidence_batch", "remain_unavailable",
)
PRICE_FIELDS = ("price_value", "price_value_eur", "price_low", "price_low_eur",
                "price_high", "price_high_eur")


class SprintError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SprintError("INVALID_INPUT") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_assignments(path: Path = DEFAULT_ASSIGNMENTS) -> dict[str, Any]:
    payload = _load(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise SprintError("INVALID_ASSIGNMENTS")
    return payload


def load_unavailable_candidates(path: Path = DEFAULT_CANDIDATES) -> list[dict[str, Any]]:
    payload = _load(path)
    if isinstance(payload, dict):
        payload = payload.get("candidates")
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        raise SprintError("INVALID_CANDIDATES")
    return [r for r in payload if r.get("price_tier") == "unavailable"]


def validate_assignment(entry: dict[str, Any]) -> list[str]:
    """Validate one assignment entry against the six-class contract."""
    errors: list[str] = []
    if not isinstance(entry, dict):
        return ["entry must be an object"]
    for field in REQUIRED_FIELDS:
        if field not in entry:
            errors.append(f"missing required field: {field}")
    if entry.get("gap_class") not in GAP_CLASSES:
        errors.append(f"unknown gap class: {entry.get('gap_class')!r}")
    if entry.get("wave") not in WAVES:
        errors.append(f"invalid wave assignment: {entry.get('wave')!r}")
    if entry.get("tier") != "unavailable":
        errors.append("unsupported price claim: sprint entries must be unavailable")
    if entry.get("remain_unavailable") is not True:
        errors.append("remain_unavailable must be true")
    for field in ("required_evidence", "best_source_type", "next_action"):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            errors.append(f"empty or invalid {field}")
    if not isinstance(entry.get("next_evidence_batch"), bool):
        errors.append("next_evidence_batch must be a boolean")
    return errors


def validate_candidate_claim(candidate: dict[str, Any]) -> list[str]:
    """Reject unsupported price/provenance claims in an unavailable candidate."""
    errors: list[str] = []
    if candidate.get("price_tier") != "unavailable":
        errors.append("candidate is not unavailable")
    for field in PRICE_FIELDS:
        if candidate.get(field) is not None:
            errors.append(f"unsupported price claim: {field} is not null")
    return errors


def validate_batch(entries: Iterable[dict[str, Any]],
                   candidates: Iterable[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    entries = list(entries)
    candidates = list(candidates)

    seen: dict[tuple[str, str], int] = {}
    for index, entry in enumerate(entries, 1):
        errors.extend(f"entry {index}: {e}" for e in validate_assignment(entry))
        key = (str(entry.get("brand", "")).casefold(), str(entry.get("model", "")).casefold())
        if key in seen:
            errors.append(f"duplicate model identity: {entry.get('brand')}/{entry.get('model')}")
        else:
            seen[key] = index

    by_identity = {
        (str(c.get("brand", "")).casefold(), str(c.get("model", "")).casefold()): c
        for c in candidates
    }
    if len(by_identity) != len(candidates):
        errors.append("duplicate model identity in source candidates")
    for entry in entries:
        key = (str(entry.get("brand", "")).casefold(), str(entry.get("model", "")).casefold())
        candidate = by_identity.get(key)
        if candidate is None:
            errors.append(f"assignment without unavailable candidate: {entry.get('brand')}/{entry.get('model')}")
            continue
        errors.extend(f"{entry.get('model')}: {e}" for e in validate_candidate_claim(candidate))
    if len(entries) != len(candidates):
        errors.append(f"assignment/candidate count mismatch: {len(entries)} != {len(candidates)}")
    return errors


def build_output(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Emit only the required output fields in deterministic order."""
    ordered = sorted(entries, key=lambda e: (e["wave"], e["brand"].casefold(), e["model"].casefold()))
    return [{field: entry[field] for field in REQUIRED_FIELDS} for entry in ordered]


def generate(candidates_path: Path = DEFAULT_CANDIDATES,
             assignments_path: Path = DEFAULT_ASSIGNMENTS) -> dict[str, Any]:
    assignments = load_assignments(assignments_path)
    entries = assignments["entries"]
    candidates = load_unavailable_candidates(candidates_path)
    errors = validate_batch(entries, candidates)
    if errors:
        raise SprintError("VALIDATION_FAILED:" + " | ".join(errors[:5]))
    return {
        "schema_version": 1,
        "artifact": "pilot-evidence-sprint-002",
        "deterministic": True,
        "candidate_sha256": _sha256(candidates_path),
        "assignment_sha256": _sha256(assignments_path),
        "candidate_count": len(candidates),
        "wave_counts": {str(w): sum(1 for e in entries if e["wave"] == w) for w in sorted(WAVES)},
        "gap_class_counts": {
            g: sum(1 for e in entries if e["gap_class"] == g) for g in sorted(GAP_CLASSES)
        },
        "catalog_writes": 0,
        "staging_writes": 0,
        "provider_calls": 0,
        "entries": build_output(entries),
    }


def safe_report_path(path: Path, root: Path = ROOT) -> Path:
    """Permit only docs/research or docs/operations artifacts; block catalog/staging."""
    resolved = path.resolve()
    blocked = [(root / "catalog").resolve(), (root / "catalog/variants").resolve(),
               (root / "staging").resolve()]
    for prefix in blocked:
        if resolved == prefix or prefix in resolved.parents:
            raise SprintError("UNSAFE_REPORT_PATH")
    allowed = [(root / "docs/research").resolve(), (root / "docs/operations").resolve()]
    if not any(resolved == base or base in resolved.parents for base in allowed):
        raise SprintError("UNSAFE_REPORT_PATH")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--assignments", type=Path, default=DEFAULT_ASSIGNMENTS)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = parser.parse_args(argv)
    try:
        payload = generate(args.candidates, args.assignments)
        if args.report is not None:
            if args.check:
                parser.error("--check must not be combined with --report")
            target = safe_report_path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    except SprintError as exc:
        print(f"EVIDENCE_SPRINT_BLOCKED: {exc.code}", file=sys.stderr)
        return 3
    print(json.dumps({
        "candidate_count": payload["candidate_count"],
        "wave_counts": payload["wave_counts"],
        "gap_class_counts": payload["gap_class_counts"],
        "catalog_writes": payload["catalog_writes"],
        "staging_writes": payload["staging_writes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
