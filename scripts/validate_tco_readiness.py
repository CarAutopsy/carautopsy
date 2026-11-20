"""Report whether catalog variants contain inputs accepted by the Austrian TCO engine."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "catalog" / "variants"
SUPPORTED_POWERTRAINS = {"bev", "ice_petrol", "ice_diesel", "hev", "phev"}
COMBUSTION_POWERTRAINS = {"ice_petrol", "ice_diesel", "hev", "phev"}


def _value(record: Any, path: str) -> Any:
    value = record
    for part in path.split("."):
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _finite_number(record: dict[str, Any], path: str, *, positive: bool = False) -> bool:
    value = _value(record, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        if not math.isfinite(value):
            return False
    except (OverflowError, TypeError):
        return False
    return value > 0 if positive else value >= 0


def _date_value(record: dict[str, Any]) -> date | None:
    raw = _value(record, "registration.first_registration_date")
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _consumption_available(record: dict[str, Any], base: str) -> bool:
    # Match calculate_tco's truthy precedence exactly. A malformed truthy
    # real_world value must not be hidden by a valid WLTP fallback.
    for key in ("real_world", "wltp_combined"):
        value = _value(record, f"{base}.{key}")
        if value:
            return _finite_number(record, f"{base}.{key}", positive=True)
    return False


def validate_variant_readiness(
    record: dict[str, Any], taxes: dict[str, Any] | None = None
) -> list[str]:
    """Return all readiness findings; malformed nested data never aborts a catalog scan."""
    issues: list[str] = []
    identity = record.get("identity")
    if not isinstance(identity, dict):
        issues.append("identity must be an object")
        identity = {}
    powertrain = identity.get("powertrain")
    vehicle_class = identity.get("vehicle_class")

    if not isinstance(powertrain, str):
        issues.append("identity.powertrain must be a string")
    elif powertrain not in SUPPORTED_POWERTRAINS:
        issues.append(f"unsupported identity.powertrain: {powertrain}")

    if not isinstance(vehicle_class, str):
        issues.append("identity.vehicle_class must be a string")
    elif vehicle_class != "M1":
        issues.append(f"unsupported identity.vehicle_class: {vehicle_class}")

    year_from = identity.get("model_year_from")
    year_to = identity.get("model_year_to")
    if year_from is not None and (isinstance(year_from, bool) or not isinstance(year_from, int)):
        issues.append("identity.model_year_from must be an integer when present")
    if year_to is not None and (isinstance(year_to, bool) or not isinstance(year_to, int)):
        issues.append("identity.model_year_to must be an integer when present")
    if (
        isinstance(year_from, int) and not isinstance(year_from, bool)
        and isinstance(year_to, int) and not isinstance(year_to, bool)
        and year_from > year_to
    ):
        issues.append("identity.model_year_from must not exceed identity.model_year_to")

    raw_registration_date = _value(record, "registration.first_registration_date")
    registration_date = _date_value(record)
    if registration_date is None:
        if raw_registration_date is None:
            issues.append("registration.first_registration_date")
        else:
            issues.append("registration.first_registration_date must be a valid ISO date")

    mass_path = "dimensions.max_permissible_mass_kg"
    if not _finite_number(record, mass_path, positive=True):
        issues.append(f"{mass_path} must be a finite positive number")
    else:
        mass = _value(record, mass_path)
        if mass > 3500:
            issues.append(f"{mass_path} exceeds the engine limit of 3500 kg")

    if powertrain == "bev":
        for path in ("performance.electric_motor_continuous_power_w",
                     "dimensions.own_weight_kg"):
            if _value(record, path) is None:
                issues.append(path)
            elif not _finite_number(record, path, positive=True):
                issues.append(f"{path} must be a finite positive number")
        if not _consumption_available(record, "energy.consumption_wh_km"):
            issues.append("energy.consumption_wh_km.real_world or wltp_combined must be a finite positive number")
    elif isinstance(powertrain, str) and powertrain in COMBUSTION_POWERTRAINS:
        for path in ("performance.combustion_engine_power_w",):
            if _value(record, path) is None:
                issues.append(path)
            elif not _finite_number(record, path, positive=True):
                issues.append(f"{path} must be a finite positive number")
        co2_path = ("emissions.co2_wltp_weighted_combined_gpkm"
                    if powertrain == "phev" else "emissions.co2_wltp_gpkm")
        if _value(record, co2_path) is None:
            issues.append(co2_path)
        elif not _finite_number(record, co2_path):
            issues.append(f"{co2_path} must be a finite non-negative number")
        if not _consumption_available(record, "extensions.fuel_consumption_l_100km"):
            issues.append("extensions.fuel_consumption_l_100km.real_world or wltp_combined must be a finite positive number")
        if not _finite_number(record, "offers.0.purchase_price_excl_vat_eur", positive=True):
            issues.append("offers[0].purchase_price_excl_vat_eur must be a finite positive number")

    # Validate year-specific statutory coverage against the exact tax pack used
    # by the publisher. This catches valid-looking records the calculator rejects.
    if (taxes is not None and registration_date is not None
            and isinstance(powertrain, str) and powertrain in SUPPORTED_POWERTRAINS):
        year = registration_date.year
        nova_exemptions = (taxes.get("nova") or {}).get("exemptions") or []
        if powertrain not in nova_exemptions:
            nova_years = (taxes.get("nova") or {}).get("annual_rules") or {}
            if year not in nova_years and str(year) not in nova_years:
                issues.append(f"NoVA rules unavailable for first-registration year {year}")
            if year == 2025 and registration_date < date(2025, 7, 1):
                issues.append("NoVA rules unavailable before 2025-07-01")
        motor_rules = (taxes.get("motorbezogene_versicherungssteuer") or {})
        if powertrain == "bev":
            if not motor_rules.get("bev_m1"):
                issues.append("motorbezogene_versicherungssteuer.bev_m1 schedule is unavailable")
        else:
            kind = "phev" if powertrain == "phev" else "ice"
            annual = motor_rules.get("annual_rules") or {}
            year_rules = annual.get(year, annual.get(str(year), {})) or {}
            if not year_rules.get(kind):
                issues.append(f"Motor-tax {kind.upper()} rules unavailable for first-registration year {year}")

    return issues


def validate_catalog_readiness(
    catalog_dir: Path = DEFAULT_CATALOG, taxes: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Return findings for each JSON record without inventing defaults."""
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
        issues = validate_variant_readiness(record, taxes)
        if issues:
            variant_id = record.get("variant_id")
            findings.append({"variant_id": variant_id if isinstance(variant_id, str) else path.stem,
                             "issues": issues})
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
    return 1 if findings and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
