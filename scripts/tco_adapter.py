"""Offline adapter: validated records -> TCO-ready engine inputs.

The adapter maps only fields explicitly supported by the Austrian TCO engine.
It never calculates TCO, modifies the engine, changes tax rules, writes catalog
or staging records, or invents a missing value.
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
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from validate_tco_readiness import SUPPORTED_POWERTRAINS  # noqa: E402

EVIDENCE_STATUSES = ("verified", "approximate", "unavailable", "owner_decision_required")

# (engine path, accepted source paths, mandatory, value validator)
FIELD_MAP: tuple[tuple[str, tuple[str, ...], bool, str], ...] = (
    ("variant_id", ("variant_id",), True, "string"),
    ("identity.make", ("identity.make",), False, "string"),
    ("identity.model", ("identity.model",), False, "string"),
    ("identity.variant_name", ("identity.variant_name", "identity.variant"), False, "string"),
    ("identity.powertrain", ("identity.powertrain",), True, "powertrain"),
    ("identity.vehicle_class", ("identity.vehicle_class",), True, "string"),
    ("registration.first_registration_date", ("registration.first_registration_date",), True, "date"),
    ("dimensions.max_permissible_mass_kg", ("dimensions.max_permissible_mass_kg",), True, "positive_number"),
    ("dimensions.own_weight_kg", ("dimensions.own_weight_kg",), True, "positive_number"),
    ("performance.electric_motor_continuous_power_w", ("performance.electric_motor_continuous_power_w",), True, "positive_number"),
    ("performance.combustion_engine_power_w", ("performance.combustion_engine_power_w",), True, "positive_number"),
    ("emissions.co2_wltp_gpkm", ("emissions.co2_wltp_gpkm",), True, "nonnegative_number"),
    ("energy.consumption_wh_km.real_world", ("energy.consumption_wh_km.real_world",), True, "positive_number"),
    ("energy.consumption_wh_km.wltp_combined", ("energy.consumption_wh_km.wltp_combined",), False, "positive_number"),
    ("extensions.fuel_consumption_l_100km.real_world", ("extensions.fuel_consumption_l_100km.real_world",), True, "positive_number"),
    ("extensions.fuel_consumption_l_100km.wltp_combined", ("extensions.fuel_consumption_l_100km.wltp_combined",), False, "positive_number"),
    ("offers.0.purchase_price_excl_vat_eur", ("offers.0.purchase_price_excl_vat_eur",), True, "positive_number"),
    ("offers.0.list_price_minor", ("offers.0.list_price_minor",), False, "nonnegative_number"),
    ("provenance.confidence", ("provenance.confidence",), False, "string"),
)

BEV_ONLY = ("performance.electric_motor_continuous_power_w", "energy.consumption_wh_km.real_world")
ICE_ONLY = ("performance.combustion_engine_power_w", "extensions.fuel_consumption_l_100km.real_world")


class AdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError("INVALID_INPUT") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _get(record: dict[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _set(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _valid_value(kind: str, value: Any) -> bool:
    if kind == "string":
        return isinstance(value, str) and bool(value.strip())
    if kind == "powertrain":
        return isinstance(value, str) and value in SUPPORTED_POWERTRAINS
    if kind == "date":
        if not isinstance(value, str):
            return False
        try:
            date.fromisoformat(value[:10])
        except ValueError:
            return False
        return True
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if kind == "positive_number":
        return value > 0
    if kind == "nonnegative_number":
        return value >= 0
    return False


def _field_provenance(record: dict[str, Any], engine_path: str) -> dict[str, Any]:
    annotations = record.get("field_provenance")
    annotation = annotations.get(engine_path) if isinstance(annotations, dict) else None
    if not isinstance(annotation, dict):
        annotation = {}
    price = record.get("price") if isinstance(record.get("price"), dict) else {}
    price_tier = price.get("price_tier")
    if engine_path == "offers.0.purchase_price_excl_vat_eur" and price_tier == "approximate":
        status = "approximate"
    elif annotation.get("status") in EVIDENCE_STATUSES:
        status = annotation["status"]
    else:
        status = "verified" if annotation.get("source_url") else "owner_decision_required"
    return {
        "status": status,
        "source_url": annotation.get("source_url") or price.get("source_url"),
        "source_date": annotation.get("source_date") or price.get("source_date"),
        "confidence": annotation.get("confidence") or price.get("confidence"),
        "price_tier": price_tier,
        "market": annotation.get("market") or price.get("market"),
        "vat_basis": annotation.get("vat_basis") or price.get("vat_basis"),
        "limitation": annotation.get("limitation"),
    }


def _applicable_mandatory(engine_path: str, powertrain: str | None) -> bool:
    if engine_path in BEV_ONLY:
        return powertrain == "bev"
    if engine_path in ICE_ONLY:
        return powertrain in {"ice_petrol", "ice_diesel", "hev", "phev"}
    return True


def adapt_record(record: dict[str, Any]) -> dict[str, Any]:
    """Produce a report for one record; never mutate the input."""
    variant_id = record.get("variant_id") if isinstance(record, dict) else None
    if not isinstance(record, dict):
        return {
            "variant_id": variant_id, "accepted": False,
            "tco_input": None, "mapped_fields": [], "unmapped_fields": [],
            "missing_mandatory_inputs": ["record"], "approximate_fields": [],
            "unavailable_fields": [], "owner_decision_fields": [],
            "validation_failures": ["record must be a JSON object"],
            "provenance": [], "tco_calculated": False, "engine_invoked": False,
        }

    powertrain = _get(record, "identity.powertrain")
    mapped: dict[str, Any] = {}
    provenance: list[dict[str, Any]] = []
    mapped_fields: list[str] = []
    unmapped: list[str] = []
    missing: list[str] = []
    approximate: list[str] = []
    unavailable: list[str] = []
    owner_decision: list[str] = []
    validation_failures: list[str] = []

    for engine_path, sources, mandatory, kind in FIELD_MAP:
        raw = next((_get(record, source) for source in sources if _get(record, source) is not None), None)
        applicable = _applicable_mandatory(engine_path, powertrain if isinstance(powertrain, str) else None)
        if raw is None:
            unmapped.append(engine_path)
            if mandatory and applicable:
                missing.append(engine_path)
            unavailable.append(engine_path)
            continue
        if not _valid_value(kind, raw):
            validation_failures.append(f"{engine_path} has unsupported value")
            unmapped.append(engine_path)
            if mandatory and applicable:
                missing.append(engine_path)
            continue
        prov = _field_provenance(record, engine_path)
        if prov["status"] == "owner_decision_required":
            owner_decision.append(engine_path)
            unmapped.append(engine_path)
            if mandatory and applicable:
                missing.append(engine_path)
            provenance.append({"field": engine_path, **prov})
            continue
        if prov["status"] == "approximate":
            approximate.append(engine_path)
        _set(mapped, engine_path, raw)
        mapped_fields.append(engine_path)
        provenance.append({"field": engine_path, **prov})

    accepted = not missing and not validation_failures
    return {
        "variant_id": variant_id,
        "accepted": accepted,
        "tco_input": mapped if accepted else None,
        "mapped_fields": sorted(mapped_fields),
        "unmapped_fields": sorted(unmapped),
        "missing_mandatory_inputs": sorted(missing),
        "approximate_fields": sorted(approximate),
        "unavailable_fields": sorted(unavailable),
        "owner_decision_fields": sorted(owner_decision),
        "validation_failures": sorted(validation_failures),
        "provenance": provenance,
        "tco_calculated": False,
        "engine_invoked": False,
    }


def generate(input_path: Path) -> dict[str, Any]:
    records = _read_json(input_path)
    if isinstance(records, dict):
        records = records.get("records")
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise AdapterError("INVALID_INPUT")
    adapted = [adapt_record(record) for record in records]
    adapted.sort(key=lambda r: str(r.get("variant_id") or ""))
    return {
        "schema_version": 1,
        "artifact": "tco-adapter",
        "deterministic": True,
        "input_files": [{"path": str(input_path), "sha256": _sha256(input_path), "read_only": True}],
        "record_count": len(records),
        "accepted_count": sum(1 for r in adapted if r["accepted"]),
        "rejected_count": sum(1 for r in adapted if not r["accepted"]),
        "records": adapted,
        "catalog_writes": 0,
        "staging_writes": 0,
        "provider_calls": 0,
        "tco_calculations": 0,
        "business_rules_changed": False,
    }


def safe_report_path(path: Path, root: Path = ROOT) -> Path:
    resolved = path.resolve()
    for prefix in ((root / "catalog").resolve(), (root / "catalog/variants").resolve(),
                   (root / "staging").resolve()):
        if resolved == prefix or prefix in resolved.parents:
            raise AdapterError("UNSAFE_REPORT_PATH")
    allowed = ((root / "docs/research").resolve(), (root / "docs/operations").resolve())
    if not any(resolved == base or base in resolved.parents for base in allowed):
        raise AdapterError("UNSAFE_REPORT_PATH")
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
    except AdapterError as exc:
        print(f"TCO_ADAPTER_BLOCKED: {exc.code}", file=sys.stderr)
        return 3
    print(json.dumps({
        "record_count": payload["record_count"],
        "accepted_count": payload["accepted_count"],
        "rejected_count": payload["rejected_count"],
        "catalog_writes": payload["catalog_writes"],
        "tco_calculations": payload["tco_calculations"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
