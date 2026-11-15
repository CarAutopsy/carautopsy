"""Report whether catalog variants contain the inputs required by the Austrian TCO engine.

Default mode is advisory so sparse research records remain valid catalog entries.
Use --strict in calculation/publication paths to fail closed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "catalog" / "variants"
NOVA_EXEMPT_POWERTRAINS = {"bev", "fcev"}
SUPPORTED_COMBUSTION_POWERTRAINS = {"ice_petrol", "ice_diesel", "hev", "phev"}


def _present(record: dict[str, Any], path: str) -> bool:
    value: Any = record
    for part in path.split("."):
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return False
    return value is not None and not isinstance(value, bool)


def validate_variant_readiness(record: dict[str, Any]) -> list[str]:
    """Return missing/unsupported TCO inputs for one catalog record."""
    missing: list[str] = []
    for path in ("identity.powertrain", "identity.vehicle_class",
                 "registration.first_registration_date",
                 "dimensions.max_permissible_mass_kg"):
        if not _present(record, path):
            missing.append(path)

    powertrain = (record.get("identity") or {}).get("powertrain")
    vehicle_class = (record.get("identity") or {}).get("vehicle_class")
    if vehicle_class is not None and vehicle_class != "M1":
        missing.append(f"unsupported identity.vehicle_class: {vehicle_class}")
    if powertrain not in NOVA_EXEMPT_POWERTRAINS | SUPPORTED_COMBUSTION_POWERTRAINS:
        missing.append(f"unsupported identity.powertrain: {powertrain}")

    if powertrain == "bev":
        for path in ("performance.electric_motor_continuous_power_w",
                     "dimensions.own_weight_kg"):
            if not _present(record, path):
                missing.append(path)
        if not any(_present(record, f"energy.consumption_wh_km.{key}")
                   for key in ("real_world", "wltp_combined")):
            missing.append("energy.consumption_wh_km.real_world or wltp_combined")
    elif powertrain in SUPPORTED_COMBUSTION_POWERTRAINS:
        if not _present(record, "performance.combustion_engine_power_w"):
            missing.append("performance.combustion_engine_power_w")
        co2_path = ("emissions.co2_wltp_weighted_combined_gpkm"
                    if powertrain == "phev" else "emissions.co2_wltp_gpkm")
        if not _present(record, co2_path):
            missing.append(co2_path)
        if not any(_present(record, f"extensions.fuel_consumption_l_100km.{key}")
                   for key in ("real_world", "wltp_combined")):
            missing.append("extensions.fuel_consumption_l_100km.real_world or wltp_combined")

    if powertrain not in NOVA_EXEMPT_POWERTRAINS:
        if not _present(record, "offers.0.purchase_price_excl_vat_eur"):
            missing.append("offers[0].purchase_price_excl_vat_eur")
    return missing


def validate_catalog_readiness(catalog_dir: Path = DEFAULT_CATALOG) -> list[dict[str, Any]]:
    """Return readiness findings for each JSON record; never supplies inferred defaults."""
    if not catalog_dir.is_dir():
        return [{"variant_id": "<catalog>", "issues": [f"catalog directory not found: {catalog_dir}"]}]
    files = sorted(catalog_dir.glob("*.json"))
    if not files:
        return [{"variant_id": "<catalog>", "issues": [f"no JSON records found in {catalog_dir}"]}]

    findings = []
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append({"variant_id": path.stem, "issues": [f"invalid JSON: {exc}"]})
            continue
        if not isinstance(record, dict):
            findings.append({"variant_id": path.stem, "issues": ["record must be a JSON object"]})
            continue
        issues = validate_variant_readiness(record)
        if issues:
            findings.append({"variant_id": record.get("variant_id", path.stem), "issues": issues})
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero when any record is not calculation-ready")
    parser.add_argument("--json", action="store_true", help="emit machine-readable findings")
    args = parser.parse_args(argv)
    findings = validate_catalog_readiness(args.catalog_dir)
    if args.json:
        print(json.dumps({"ready": not findings, "findings": findings}, indent=2))
    elif not findings:
        print("TCO readiness passed: all catalog records have required calculation inputs.")
    else:
        print(f"TCO readiness: {len(findings)} record(s) need input completion:")
        for item in findings:
            print(f"- {item['variant_id']}:")
            for issue in item["issues"]:
                print(f"    - {issue}")
    if findings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
