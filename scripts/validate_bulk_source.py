"""Offline validation of a sampled EU type-approval bulk source.

Reads a small UTF-8 TSV sample from the EEA CO2 passenger-car microdata, maps
each row to the CarAutopsy variant shape, and runs the existing fail-closed
readiness gate. No full dataset download, no network call, no catalog write and
no production-script change is performed by this script.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_tco_readiness import validate_variant_readiness  # noqa: E402


REQUIRED_FIELDS = (
    "variant_id",
    "identity.make",
    "identity.model",
    "identity.powertrain",
    "identity.vehicle_class",
    "registration.first_registration_date",
    "dimensions.max_permissible_mass_kg",
    "performance.combustion_engine_power_w",
    "performance.electric_motor_continuous_power_w",
    "energy.consumption_wh_km",
    "emissions.co2_wltp_gpkm",
    "emissions.co2_nedc_gpkm",
    "offers.purchase_price_excl_vat_eur",
    "extensions.fuel_consumption",
)

# The EEA dataset uses short column codes. See docs/data-sources/bulk-source-selection.md.
COLUMNS = (
    "ID", "MS", "Mp", "VFN", "Mh", "Man", "MMS", "TAN", "T", "Va", "Ve", "Mk", "Cn",
    "Ct", "Cr", "m (kg)", "Mt", "Enedc (g/km)", "Ewltp (g/km)", "W (mm)", "At1 (mm)",
    "At2 (mm)", "Ft", "Fm", "ec (cm3)", "ep (KW)", "z (Wh/km)", "It", "Ernedc (g/km)",
    "Erwltp (g/km)", "De", "Vf", "r",
)
FUEL_MAP = {
    "PETROL": "ice_petrol",
    "DIESEL": "ice_diesel",
    "ELECTRIC": "bev",
    "HYBRID": "hev",
    "HYBRID ELECTRIC": "hev",
    "PLUG-IN HYBRID": "phev",
    "NG-BIOMETHANE": "ice_petrol",
}
MODEL_YEAR = 2017  # EEA annual microdata file used for this sample.


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "unknown"


def _number(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def read_sample(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("sample file is empty")
    header = lines[0].split("\t")
    if tuple(header) != COLUMNS:
        raise ValueError("unexpected source schema")
    records = []
    for line in lines[1:]:
        parts = (line.split("\t") + [""] * len(COLUMNS))[: len(COLUMNS)]
        if parts[1] != "AT" or not parts[0].isdigit():
            continue
        records.append(dict(zip(COLUMNS, parts)))
    return records


def map_record(row: dict[str, str]) -> dict[str, Any]:
    """Map one EEA row to the CarAutopsy variant shape, omitting unknown fields."""
    fuel = row.get("Ft", "").strip().upper()
    powertrain = FUEL_MAP.get(fuel)
    make = row.get("Mh") or row.get("Man") or "Unknown"
    model = row.get("Mk") or row.get("MMS") or "unknown"
    variant = row.get("Ve") or row.get("Va") or row.get("T") or "variant"
    power_kw = _number(row.get("ep (KW)", ""))
    mass_kg = _number(row.get("m (kg)", ""))
    co2 = _number(row.get("Ewltp (g/km)", ""))
    co2_legacy = _number(row.get("Enedc (g/km)", ""))
    electric_wh_km = _number(row.get("z (Wh/km)", ""))
    own_weight = _number(row.get("Mt", ""))

    identity: dict[str, Any] = {
        "make": make.strip(),
        "model": model.strip(),
    }
    if powertrain:
        identity["powertrain"] = powertrain
    vehicle_class = (row.get("Ct") or row.get("Cr") or "").strip().upper()
    if vehicle_class:
        identity["vehicle_class"] = vehicle_class
    if row.get("TAN", "").strip():
        identity["type_approval_number"] = row["TAN"].strip()

    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "variant_id": f"eea-{row['ID']}-{_slug(make)}-{_slug(model)}",
        "status": "draft",
        "identity": identity,
        "registration": {"first_registration_date": f"{MODEL_YEAR}-01-01"},
        "provenance": {
            "confidence": "low",
            "sources": [{"source_id": "eea-co2-mrv", "url": "https://co2cars.apps.eea.europa.eu/"}],
        },
    }

    dimensions: dict[str, Any] = {}
    if mass_kg is not None:
        dimensions["max_permissible_mass_kg"] = mass_kg
    if own_weight is not None:
        dimensions["own_weight_kg"] = own_weight
    if dimensions:
        result["dimensions"] = dimensions

    performance: dict[str, Any] = {}
    if power_kw is not None and powertrain and powertrain != "bev":
        performance["combustion_engine_power_w"] = power_kw * 1000
    if power_kw is not None and powertrain == "bev":
        performance["electric_motor_continuous_power_w"] = power_kw * 1000
    if performance:
        result["performance"] = performance

    # Never relabel legacy NEDC values as WLTP: the readiness gate and the TCO
    # engine treat those as different statutory inputs.
    if co2 is not None:
        result["emissions"] = {"co2_wltp_gpkm": co2}
    elif co2_legacy is not None:
        result["emissions"] = {"co2_nedc_gpkm": co2_legacy}
    if electric_wh_km is not None:
        result["energy"] = {"consumption_wh_km": {"wltp_combined": electric_wh_km}}
    if variant:
        result["variant_name"] = variant
    return result


def _present(record: dict[str, Any], path: str) -> bool:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return value is not None and value != ""


def validate_sample(sample_path: Path, *, with_taxes: bool = True) -> dict[str, Any]:
    rows = read_sample(sample_path)
    taxes = None
    if with_taxes:
        manifest = yaml.safe_load((ROOT / "country-packs" / "AT" / "manifest.yaml").read_text(encoding="utf-8"))
        taxes = manifest.get("taxes", manifest)
    records = [map_record(row) for row in rows]

    passed, rejected = 0, []
    for record in records:
        findings = validate_variant_readiness(record, taxes)
        if findings:
            rejected.append({"variant_id": record["variant_id"], "findings": findings})
        else:
            passed += 1

    coverage = {
        field: round(100 * sum(_present(record, field) for record in records) / len(records), 1)
        if records else 0.0
        for field in REQUIRED_FIELDS
    }
    reasons = Counter(
        finding
        for item in rejected
        for finding in item["findings"]
    )
    return {
        "source": "EEA CO2 passenger cars (public type-approval microdata)",
        "sample_file": str(sample_path.relative_to(ROOT)),
        "dataset_year": MODEL_YEAR,
        "sampled": len(rows),
        "passed": passed,
        "rejected": len(rejected),
        "statutory_rules_applied": with_taxes,
        "field_coverage_percent": coverage,
        "rejection_reasons": dict(sorted(reasons.items())),
        "rejected_records": rejected[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        default=str(ROOT / "docs" / "data-sources" / "sample" / "eea_at_2017_sample.tsv"),
        help="UTF-8 TSV sample of EEA microdata",
    )
    parser.add_argument("--no-taxes", action="store_true", help="run structural gate only")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a summary")
    args = parser.parse_args()

    report = validate_sample(Path(args.sample), with_taxes=not args.no_taxes)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"source: {report['source']}")
        print(f"sampled: {report['sampled']} passed: {report['passed']} rejected: {report['rejected']}")
        print("field coverage %:")
        for field, value in report["field_coverage_percent"].items():
            print(f"  {field}: {value}")
        print("rejection reasons:")
        for reason, count in report["rejection_reasons"].items():
            print(f"  {count}x {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
