"""Offline deterministic identity normalization and conflict detection.

Reads synthetic or committed candidate records read-only, compares them against
each other and optionally against a read-only catalog snapshot, and emits a
structured conflict report. It never merges, overwrites, deletes, promotes,
writes catalog or staging records, or assigns a price.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from catalog_quality import normalize_identity  # noqa: E402

CLASSES = (
    "exact_duplicate",
    "probable_duplicate_owner_review",
    "conflicting_attribute",
    "missing_mandatory_identity_field",
    "unsupported_identity_assertion",
    "unresolved_variant",
)

COMPARE_FIELDS = (
    "model_year", "body_style", "powertrain", "trim", "battery_capacity",
    "range", "dimensions", "weight", "price_evidence", "source_provenance",
)


class ConflictError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConflictError("INVALID_INPUT") from exc


def _input_descriptor(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "read_only": True,
    }


def guard_input_path(path: Path, root: Path = ROOT) -> Path:
    """Refuse to read the real staging batch or live catalog as tool input."""
    resolved = path.resolve()
    blocked = [(root / "staging").resolve(), (root / "catalog/variants").resolve()]
    for prefix in blocked:
        if resolved == prefix or prefix in resolved.parents:
            raise ConflictError("BLOCKED_INPUT_PATH")
    return resolved


def safe_report_path(path: Path, root: Path = ROOT) -> Path:
    resolved = path.resolve()
    for prefix in ((root / "catalog").resolve(), (root / "catalog/variants").resolve(),
                   (root / "staging").resolve()):
        if resolved == prefix or prefix in resolved.parents:
            raise ConflictError("UNSAFE_REPORT_PATH")
    allowed = ((root / "docs/research").resolve(), (root / "docs/operations").resolve())
    if not any(resolved == base or base in resolved.parents for base in allowed):
        raise ConflictError("UNSAFE_REPORT_PATH")
    return resolved


def _values(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("identity") if isinstance(record.get("identity"), dict) else {}
    spec = record.get("spec") if isinstance(record.get("spec"), dict) else {}
    price = record.get("price") if isinstance(record.get("price"), dict) else {}
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    sources = provenance.get("sources")
    return {
        "model_year": identity.get("model_year"),
        "body_style": spec.get("body_style"),
        "powertrain": identity.get("powertrain"),
        "trim": identity.get("trim") or spec.get("trim"),
        "battery_capacity": spec.get("battery_capacity_kwh"),
        "range": spec.get("range_km"),
        "dimensions": spec.get("dimensions"),
        "weight": spec.get("weight_kg"),
        "price_evidence": {
            "price_tier": price.get("price_tier"),
            "price_value": price.get("price_value"),
            "source_url": price.get("source_url"),
            "source_date": price.get("source_date"),
            "vat_basis": price.get("vat_basis"),
        },
        "source_provenance": sources,
    }


def _source(record: dict[str, Any]) -> Any:
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    sources = provenance.get("sources")
    if isinstance(sources, list) and sources:
        return sources[0]
    price = record.get("price") if isinstance(record.get("price"), dict) else {}
    return {
        "source_url": price.get("source_url"),
        "source_date": price.get("source_date"),
        "vat_basis": price.get("vat_basis"),
    }


def _identity_label(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant_id": record.get("variant_id"),
        "make": (record.get("identity") or {}).get("make"),
        "model": (record.get("identity") or {}).get("model"),
        "variant": (record.get("identity") or {}).get("variant"),
        "model_year": (record.get("identity") or {}).get("model_year"),
    }


def _canonical(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("identity") if isinstance(record.get("identity"), dict) else {}
    shim = dict(identity)
    shim["variant_name"] = identity.get("variant") or identity.get("variant_name")
    return normalize_identity({"identity": shim}, str(record.get("variant_id") or "fixture"))


def _finding(identity: dict[str, Any], field: str, competing: list[Any],
             provenance: list[Any], category: str, recommendation: str,
             owner: bool = True) -> dict[str, Any]:
    return {
        "candidate_identity": identity,
        "conflicting_field": field,
        "competing_values": competing,
        "source_provenance": provenance,
        "recommended_resolution": category,
        "owner_decision_required": owner,
        "action": recommendation,
    }


def _record_findings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for record in records:
        identity = record.get("identity") if isinstance(record.get("identity"), dict) else {}
        missing = [f for f in ("make", "model") if not identity.get(f)]
        if missing:
            findings.append(_finding(
                _identity_label(record), "identity", missing, [_source(record)],
                "missing_mandatory_identity_field", "owner_supplies_missing_identity"))
        unsupported = [
            f for f in ("make", "model", "variant")
            if f in identity and identity[f] is not None and not isinstance(identity[f], str)
        ]
        if "model_year" in identity and identity["model_year"] is not None \
                and (isinstance(identity["model_year"], bool) or not isinstance(identity["model_year"], int)):
            unsupported.append("model_year")
        if unsupported:
            findings.append(_finding(
                _identity_label(record), "identity", unsupported, [_source(record)],
                "unsupported_identity_assertion", "owner_corrects_identity_types"))
        if not identity.get("variant") and not identity.get("variant_name"):
            findings.append(_finding(
                _identity_label(record), "variant", [], [_source(record)],
                "unresolved_variant", "owner_resolves_variant"))
    return findings


def _group_findings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if len(records) < 2:
        return findings
    values = [_values(r) for r in records]
    differing = [f for f in COMPARE_FIELDS if any(v[f] != values[0][f] for v in values[1:])]
    # Case/whitespace-only identity differences canonicalize to the same key;
    # they are probable duplicates requiring owner review even when no watched
    # attribute differs.
    raw_identity_diff = any(
        (r.get("identity") or {}).get("make") != (records[0].get("identity") or {}).get("make")
        or (r.get("identity") or {}).get("model") != (records[0].get("identity") or {}).get("model")
        for r in records[1:]
    )
    if raw_identity_diff:
        findings.append(_finding(
            _identity_label(records[0]), "identity_raw",
            [((r.get("identity") or {}).get("make"), (r.get("identity") or {}).get("model")) for r in records],
            [_source(r) for r in records], "probable_duplicate_owner_review",
            "owner_reviews_raw_identity_differences"))
        return findings
    if not differing:
        findings.append(_finding(
            _identity_label(records[0]), "record", [r.get("variant_id") for r in records],
            [_source(r) for r in records], "exact_duplicate", "do_not_write_duplicate"))
        return findings
    for field in differing:
        findings.append(_finding(
            _identity_label(records[0]), field, [v[field] for v in values],
            [_source(r) for r in records], "conflicting_attribute",
            "owner_selects_supported_value"))
    return findings


def detect(candidates: list[dict[str, Any]],
           catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    findings = _record_findings(candidates)
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in candidates:
        key = _canonical(record)["canonical_key"]
        groups.setdefault(str(key), []).append(record)
    for group in groups.values():
        findings.extend(_group_findings(group))

    if catalog:
        catalog_keys = {str(_canonical(r)["canonical_key"]): r for r in catalog}
        for record in candidates:
            key = str(_canonical(record)["canonical_key"])
            if key in catalog_keys:
                existing = catalog_keys[key]
                findings.append(_finding(
                    _identity_label(record), "existing_catalog_record",
                    [record.get("variant_id"), existing.get("variant_id")],
                    [_source(record), _source(existing)], "exact_duplicate",
                    "do_not_write_existing_catalog_duplicate"))
    findings.sort(key=lambda f: (
        str(f["candidate_identity"].get("variant_id") or ""),
        str(f["conflicting_field"]), str(f["recommended_resolution"]),
    ))
    return findings


def generate(candidates_path: Path, catalog_path: Path | None = None) -> dict[str, Any]:
    guard_input_path(candidates_path)
    candidates = _read_json(candidates_path)
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates")
    if not isinstance(candidates, list) or not all(isinstance(r, dict) for r in candidates):
        raise ConflictError("INVALID_INPUT")
    catalog: list[dict[str, Any]] | None = None
    inputs = [_input_descriptor(candidates_path)]
    if catalog_path is not None:
        guard_input_path(catalog_path)
        catalog = _read_json(catalog_path)
        if not isinstance(catalog, list) or not all(isinstance(r, dict) for r in catalog):
            raise ConflictError("INVALID_INPUT")
        inputs.append(_input_descriptor(catalog_path))
    findings = detect(candidates, catalog)
    return {
        "schema_version": 1,
        "artifact": "identity-conflict-resolution",
        "deterministic": True,
        "input_files": inputs,
        "candidate_count": len(candidates),
        "catalog_records_read": len(catalog or []),
        "finding_count": len(findings),
        "findings": findings,
        "catalog_writes": 0,
        "staging_writes": 0,
        "provider_calls": 0,
        "records_merged": 0,
        "records_overwritten": 0,
        "records_deleted": 0,
        "records_promoted": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = parser.parse_args(argv)
    if args.check and args.report is not None:
        parser.error("--check must not be combined with --report")
    if not args.check and args.report is None:
        parser.error("--report is required unless --check is set")
    try:
        payload = generate(args.candidates, args.catalog)
        if args.report is not None:
            target = safe_report_path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                              encoding="utf-8")
    except ConflictError as exc:
        print(f"IDENTITY_CONFLICTS_BLOCKED: {exc.code}", file=sys.stderr)
        return 3
    print(json.dumps({
        "candidate_count": payload["candidate_count"],
        "finding_count": payload["finding_count"],
        "catalog_writes": payload["catalog_writes"],
        "staging_writes": payload["staging_writes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
