"""Offline, deterministic vehicle-specification ingestion for the pilot.

Reads committed/offline observation JSON only. Missing evidence stays null.
No network, provider, secret, catalog or staging write is performed.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas/vehicle-specification.schema.json"

POWERTRAINS = frozenset({"petrol", "diesel", "hybrid", "phev", "bev", "fcev", "mild_hybrid", "plugin_hybrid"})
FUEL_TYPES = frozenset({"petrol", "diesel", "electric", "hydrogen", "hybrid"})
DRIVETRAINS = frozenset({"fwd", "rwd", "awd", "4wd"})
BODY_STYLES = frozenset({"hatchback", "sedan", "suv", "crossover", "mpv", "coupe", "wagon", "van", "pickup"})
TRANSMISSIONS = frozenset({"manual", "automatic", "dsm", "single_speed", "direct_shift"})
SOURCE_TYPES = frozenset({"manufacturer", "dealer", "regulatory", "research", "owner_evidence"})
CONFIDENCES = frozenset({"low", "medium", "high"})
LICENSE_STATUSES = frozenset({"licensed", "attributed", "public_domain", "owner_review_required", "unknown"})

SPEC_FIELDS = ("battery_capacity_kwh", "electric_range_km", "weight_kg", "seats")
DIMENSION_FIELDS = ("length_mm", "width_mm", "height_mm")
BOUNDS = {
    "battery_capacity_kwh": (0.0, 300.0),
    "electric_range_km": (0.0, 2000.0),
    "weight_kg": (0.0, 10000.0),
    "seats": (0, 15),
    "length_mm": (0.0, 12000.0),
    "width_mm": (0.0, 4000.0),
    "height_mm": (0.0, 4000.0),
}


class SpecError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError("INVALID_INPUT") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _number_in_bounds(name: str, value: Any) -> bool:
    low, high = BOUNDS[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return low <= value <= high


def validate_observation(record: Any) -> list[str]:
    """Return actionable validation errors; empty means the observation is valid."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["observation must be a JSON object"]
    if not isinstance(record.get("variant_id"), str) or not record["variant_id"].strip():
        errors.append("variant_id is required")

    identity = record.get("identity")
    if not isinstance(identity, dict):
        errors.append("identity object is required")
        identity = {}
    for field in ("make", "model", "variant"):
        if not isinstance(identity.get(field), str) or not identity[field].strip():
            errors.append(f"identity.{field} is required")
    year = identity.get("model_year")
    if isinstance(year, bool) or not isinstance(year, int) or not 1990 <= year <= 2035:
        errors.append("identity.model_year must be an integer between 1990 and 2035")

    enums = (
        ("body_style", BODY_STYLES), ("powertrain", POWERTRAINS),
        ("fuel_type", FUEL_TYPES), ("drivetrain", DRIVETRAINS),
        ("transmission", TRANSMISSIONS),
    )
    for field, allowed in enums:
        value = identity.get(field)
        if value is not None and (not isinstance(value, str) or value not in allowed):
            errors.append(f"identity.{field} has unsupported value {value!r}")

    specs = record.get("specifications")
    if not isinstance(specs, dict):
        errors.append("specifications object is required")
        specs = {}
    for field in SPEC_FIELDS:
        value = specs.get(field)
        if value is not None and not _number_in_bounds(field, value):
            errors.append(f"specifications.{field} has invalid value or unit")
    dimensions = specs.get("dimensions")
    if dimensions is not None and not isinstance(dimensions, dict):
        errors.append("specifications.dimensions must be an object or null")
    else:
        for field in DIMENSION_FIELDS:
            value = (dimensions or {}).get(field)
            if value is not None and not _number_in_bounds(field, value):
                errors.append(f"specifications.dimensions.{field} has invalid value or unit")

    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance object is required")
        provenance = {}
    for field in ("source_id",):
        if not isinstance(provenance.get(field), str) or not provenance[field].strip():
            errors.append(f"provenance.{field} is required")
    url = provenance.get("source_url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        errors.append("provenance.source_url must be an http(s) URL")
    if not _valid_date(provenance.get("retrieval_date")):
        errors.append("provenance.retrieval_date must be ISO YYYY-MM-DD")
    source_type = provenance.get("source_type")
    if source_type not in SOURCE_TYPES:
        errors.append(f"provenance.source_type has unsupported value {source_type!r}")
    confidence = provenance.get("confidence")
    if confidence not in CONFIDENCES:
        errors.append("provenance.confidence must be low, medium or high")
    license_status = provenance.get("license_attribution_status")
    if license_status not in LICENSE_STATUSES:
        errors.append("provenance.license_attribution_status has unsupported value")
    return errors


def identity_key(record: dict[str, Any]) -> tuple[str, str, str, int | None]:
    """Detection-only key; stored identity fields are never rewritten."""
    identity = record.get("identity") if isinstance(record.get("identity"), dict) else {}
    return (
        str(identity.get("make", "")).strip().casefold(),
        str(identity.get("model", "")).strip().casefold(),
        str(identity.get("variant", "")).strip().casefold(),
        identity.get("model_year"),
    )


def canonical_record(record: dict[str, Any], status: str) -> dict[str, Any]:
    """Build the canonical record, copying supplied values without inference."""
    identity = record.get("identity") if isinstance(record.get("identity"), dict) else {}
    specs = record.get("specifications") if isinstance(record.get("specifications"), dict) else {}
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    dimensions = specs.get("dimensions") if isinstance(specs.get("dimensions"), dict) else None
    return {
        "schema_version": 1,
        "variant_id": record.get("variant_id"),
        "identity": {
            "make": identity.get("make"),
            "model": identity.get("model"),
            "variant": identity.get("variant"),
            "model_year": identity.get("model_year"),
            "body_style": identity.get("body_style"),
            "powertrain": identity.get("powertrain"),
            "fuel_type": identity.get("fuel_type"),
            "drivetrain": identity.get("drivetrain"),
            "transmission": identity.get("transmission"),
            "model_specific_id": identity.get("model_specific_id"),
        },
        "specifications": {
            "battery_capacity_kwh": specs.get("battery_capacity_kwh"),
            "electric_range_km": specs.get("electric_range_km"),
            "dimensions": {
                "length_mm": (dimensions or {}).get("length_mm"),
                "width_mm": (dimensions or {}).get("width_mm"),
                "height_mm": (dimensions or {}).get("height_mm"),
            } if dimensions is not None else None,
            "weight_kg": specs.get("weight_kg"),
            "seats": specs.get("seats"),
        },
        "provenance": {
            "source_id": provenance.get("source_id"),
            "source_url": provenance.get("source_url"),
            "retrieval_date": provenance.get("retrieval_date"),
            "source_type": provenance.get("source_type"),
            "license_attribution_status": provenance.get("license_attribution_status"),
            "confidence": provenance.get("confidence"),
            "limitation": provenance.get("limitation"),
        },
        "evidence_status": status,
    }


def _has_all_specs(record: dict[str, Any]) -> bool:
    specs = record.get("specifications") if isinstance(record.get("specifications"), dict) else {}
    if any(specs.get(field) is None for field in SPEC_FIELDS):
        return False
    dimensions = specs.get("dimensions")
    return isinstance(dimensions, dict) and all(dimensions.get(f) is not None for f in DIMENSION_FIELDS)


def detect_group_findings(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find duplicate identities and conflicting evidence within the batch."""
    groups: dict[tuple[str, str, str, int | None], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(identity_key(record), []).append(record)
    findings: list[dict[str, Any]] = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        ids = [r.get("variant_id") for r in group]
        findings.append({
            "finding_type": "duplicate_identity",
            "identity": {"make": key[0], "model": key[1], "variant": key[2], "model_year": key[3]},
            "variant_ids": ids,
            "owner_decision_required": True,
        })
        for field in SPEC_FIELDS:
            values = [r.get("specifications", {}).get(field) for r in group]
            present = [v for v in values if v is not None]
            if len(set(map(str, present))) > 1:
                findings.append({
                    "finding_type": "conflicting_evidence",
                    "identity": {"make": key[0], "model": key[1], "variant": key[2], "model_year": key[3]},
                    "field": field,
                    "competing_values": present,
                    "variant_ids": ids,
                    "owner_decision_required": True,
                })
    findings.sort(key=lambda f: (f["finding_type"], str(f.get("field", "")), str(f["variant_ids"])))
    return findings


def generate(input_path: Path) -> dict[str, Any]:
    observations = _read_json(input_path)
    if isinstance(observations, dict):
        observations = observations.get("observations")
    if not isinstance(observations, list) or not all(isinstance(r, dict) for r in observations):
        raise SpecError("INVALID_INPUT")

    rejected: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for record in observations:
        errors = validate_observation(record)
        if errors:
            rejected.append({"variant_id": record.get("variant_id"), "errors": errors})
        else:
            accepted.append(record)

    findings = detect_group_findings(accepted)
    conflicting_ids = {vid for f in findings if f["finding_type"] == "conflicting_evidence"
                       for vid in f["variant_ids"]}
    records = []
    for record in accepted:
        status = "conflicting" if record.get("variant_id") in conflicting_ids else (
            "complete" if _has_all_specs(record) else "partial")
        records.append(canonical_record(record, status))
    records.sort(key=lambda r: (str(r.get("variant_id") or ""),))

    return {
        "schema_version": 1,
        "artifact": "vehicle-specification-ingestion",
        "deterministic": True,
        "input_files": [{"path": str(input_path), "sha256": _sha256(input_path), "read_only": True}],
        "observation_count": len(observations),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "finding_count": len(findings),
        "records": records,
        "rejected": rejected,
        "findings": findings,
        "catalog_writes": 0,
        "staging_writes": 0,
        "provider_calls": 0,
        "no_value_inferred": True,
    }


def safe_report_path(path: Path, root: Path = ROOT) -> Path:
    resolved = path.resolve()
    for prefix in ((root / "catalog").resolve(), (root / "catalog/variants").resolve(),
                   (root / "staging").resolve()):
        if resolved == prefix or prefix in resolved.parents:
            raise SpecError("UNSAFE_REPORT_PATH")
    allowed = ((root / "docs/research").resolve(), (root / "docs/operations").resolve())
    if not any(resolved == base or base in resolved.parents for base in allowed):
        raise SpecError("UNSAFE_REPORT_PATH")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = parser.parse_args(argv)
    if args.check and args.report is not None:
        parser.error("--check must not be combined with --report")
    if not args.check and args.report is None:
        parser.error("--report is required unless --check is set")
    try:
        payload = generate(args.input)
        if args.report is not None:
            target = safe_report_path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                              encoding="utf-8")
    except SpecError as exc:
        print(f"SPEC_INGESTION_BLOCKED: {exc.code}", file=sys.stderr)
        return 3
    print(json.dumps({
        "observation_count": payload["observation_count"],
        "accepted_count": payload["accepted_count"],
        "rejected_count": payload["rejected_count"],
        "finding_count": payload["finding_count"],
        "catalog_writes": payload["catalog_writes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
