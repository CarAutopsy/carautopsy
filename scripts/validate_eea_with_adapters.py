"""Attributed EEA adapter: derived consumption, price-pending and proposal artifacts.

Offline and deterministic. Reads a sampled EEA type-approval TSV, maps it to the
CarAutopsy variant shape with explicitly attributed derived inputs, runs the
existing readiness gate, and emits proposal artifacts under
``docs/data-sources/proposals/`` only. It never writes ``catalog/variants/``,
never downloads a dataset, never reads secrets and never activates retrieval.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_tco_readiness import validate_variant_readiness  # noqa: E402
from validate_bulk_source import COLUMNS, FUEL_MAP, _number, _slug  # noqa: E402


MIN_WLTP_YEAR = 2018
MAX_WLTP_YEAR = 2026
NEDC_REJECTION = "NEDC-only file, WLTP required"
SOURCE_NAME = "EEA type-approval CO2 microdata"
SOURCE_URL = "https://www.eea.europa.eu/data-and-maps/data/co2-cars-emission-20"
SOURCE_LICENSE = "CC BY 4.0"
DERIVED_FROM = "co2_nedc_wltp"
CO2_DIVISOR = {"ice_petrol": 23.2, "ice_diesel": 26.5}
PROPOSALS_ROOT = ROOT / "docs" / "data-sources" / "proposals"
GATE_FIELDS = (
    "identity.make",
    "identity.model",
    "identity.powertrain",
    "identity.vehicle_class",
    "registration.first_registration_date",
    "dimensions.max_permissible_mass_kg",
    "performance.combustion_engine_power_w",
    "extensions.fuel_consumption_l_100km.real_world",
    "offers.price_or_pending",
)


def is_wltp_era(year: Any) -> bool:
    """Only 2018–2026 type-approval years are accepted for this pilot."""
    return (
        isinstance(year, int) and not isinstance(year, bool)
        and MIN_WLTP_YEAR <= year <= MAX_WLTP_YEAR
    )


def derive_fuel_consumption(co2_g_per_km: Any, powertrain: str | None) -> dict[str, Any] | None:
    """Derive L/100 km from CO2 with an explicit, non-measured attribution."""
    divisor = CO2_DIVISOR.get(powertrain or "")
    value = _number(str(co2_g_per_km)) if co2_g_per_km is not None else None
    if divisor is None or value is None:
        return None
    return {
        "value": round(value / divisor, 3),
        "derived": True,
        "derived_from": DERIVED_FROM,
        "conversion_formula": f"CO2_g_per_km / {divisor} = L_per_100km",
        "measured": False,
    }


def attach_price(variant_id: str, price_source: dict[str, Any] | None) -> dict[str, Any]:
    """Attach an attributed price or mark the record pending; never invent one."""
    entry = (price_source or {}).get(variant_id)
    if isinstance(entry, dict):
        value = _number(str(entry.get("price_excl_vat_eur", "")))
        if value is not None and value > 0:
            return {
                "purchase_price_excl_vat_eur": value,
                "price_pending": False,
                "price_source": entry.get("source", "unattributed"),
                "price_source_url": entry.get("url"),
            }
    return {
        "purchase_price_excl_vat_eur": None,
        "price_pending": True,
        "price_source": None,
        "price_source_url": None,
    }


def read_rows(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or tuple(lines[0].split("\t")) != COLUMNS:
        raise ValueError("sample does not match the documented EEA schema")
    rows = []
    for line in lines[1:]:
        parts = (line.split("\t") + [""] * len(COLUMNS))[:len(COLUMNS)]
        if parts[0].isdigit() and parts[1] == "AT":
            rows.append(dict(zip(COLUMNS, parts)))
    return rows


def map_row(
    row: dict[str, str],
    year: int,
    price_source: dict[str, Any] | None,
) -> dict[str, Any]:
    """Map one EEA row to a variant plus attributed derived fields."""
    fuel = row.get("Ft", "").strip().upper()
    powertrain = FUEL_MAP.get(fuel)
    make = (row.get("Mh") or row.get("Man") or "Unknown").strip()
    model = (row.get("Mk") or row.get("MMS") or "unknown").strip()
    variant = (row.get("Ve") or row.get("Va") or row.get("T") or "variant").strip()
    variant_id = f"eea-{row['ID']}-{_slug(make)}-{_slug(model)}"

    co2 = _number(row.get("Ewltp (g/km)", ""))
    co2_basis = "wltp"
    if co2 is None:
        co2 = _number(row.get("Enedc (g/km)", ""))
        co2_basis = "nedc"
    derived = derive_fuel_consumption(co2, powertrain) if co2_basis == "nedc" else None
    price = attach_price(variant_id, price_source)

    power_kw = _number(row.get("ep (KW)", ""))
    mass_kg = _number(row.get("m (kg)", ""))
    vehicle_class = (row.get("Ct") or row.get("Cr") or "").strip().upper()

    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "variant_id": variant_id,
        "status": "proposed",
        "identity": {"make": make, "model": model, "variant_name": variant},
        "registration": {"first_registration_date": f"{year}-01-01"},
        "provenance": {
            "confidence": "low",
            "sources": [{
                "source_id": "eea-co2-mrv",
                "url": SOURCE_URL,
                "license": SOURCE_LICENSE,
                "record_id": row.get("ID", ""),
            }],
        },
        "source_fields": {
            "record_id": row.get("ID", ""),
            "make": make,
            "model": model,
            "variant": variant,
            "powertrain": powertrain,
            "vehicle_class": vehicle_class,
            "mass_kg": mass_kg,
            "power_kw": power_kw,
            "co2_g_per_km": co2,
            "co2_basis": co2_basis,
            "fuel_code": fuel,
        },
    }
    if powertrain:
        result["identity"]["powertrain"] = powertrain
    if vehicle_class:
        result["identity"]["vehicle_class"] = vehicle_class
    if mass_kg is not None:
        result["dimensions"] = {"max_permissible_mass_kg": mass_kg}
    if power_kw is not None and powertrain in {"ice_petrol", "ice_diesel", "hev", "phev"}:
        result.setdefault("performance", {})["combustion_engine_power_w"] = power_kw * 1000
    if power_kw is not None and powertrain == "bev":
        result.setdefault("performance", {})["electric_motor_continuous_power_w"] = power_kw * 1000
    if co2 is not None:
        key = "co2_wltp_gpkm" if co2_basis == "wltp" else "co2_nedc_gpkm"
        result["emissions"] = {key: co2}
    if derived is not None:
        result["extensions"] = {
            "fuel_consumption_l_100km": {
                "real_world": derived["value"],
                "derived": True,
                "derived_from": derived["derived_from"],
                "conversion_formula": derived["conversion_formula"],
                "measured": False,
            }
        }
    result["offers"] = [price]
    result["price_pending"] = price["price_pending"]
    return result


def _present(record: dict[str, Any], path: str) -> bool:
    value: Any = record
    parts = path.split(".")
    for index, part in enumerate(parts):
        if part == "price_or_pending":
            return isinstance(value, dict) and (
                value.get("purchase_price_excl_vat_eur") is not None
                or value.get("price_pending") is True
            )
        if isinstance(value, list) and part == "offers":
            if not value or not isinstance(value[0], dict):
                return False
            value = value[0]
            continue
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
        if isinstance(value, list) and value and isinstance(value[0], dict):
            value = value[0]
    return value is not None and value != ""


def field_coverage(records: list[dict[str, Any]]) -> dict[str, float]:
    if not records:
        return {field: 0.0 for field in GATE_FIELDS}
    return {
        field: round(100 * sum(_present(record, field) for record in records) / len(records), 1)
        for field in GATE_FIELDS
    }


def proposal_path(record: dict[str, Any], year: int) -> Path:
    # The record id disambiguates repeated make/model/variant combinations.
    name = "{}.{}.{}.{}.{}.json".format(
        _slug(str(record["identity"].get("make", "unknown"))),
        _slug(str(record["identity"].get("model", "unknown"))),
        _slug(str(record["identity"].get("variant_name", "variant"))),
        year,
        _slug(str(record.get("source_fields", {}).get("record_id", "unknown"))),
    )
    return PROPOSALS_ROOT / name


def build_proposal(
    record: dict[str, Any],
    *,
    year: int,
    findings: list[str],
    dataset_year: int,
) -> dict[str, Any]:
    """Return a deterministic proposal artifact with full provenance."""
    proposal: dict[str, Any] = {
        "schema_version": 1,
        "variant": record,
        "derived_fields": {
            "fuel_consumption_l_per_100km": derive_fuel_consumption(
                record.get("source_fields", {}).get("co2_g_per_km"),
                record.get("source_fields", {}).get("powertrain"),
            )
        },
        "price": {
            "purchase_price_excl_vat_eur": record.get("offers", [{}])[0].get("purchase_price_excl_vat_eur"),
            "price_pending": record.get("price_pending", True),
            "price_source": record.get("offers", [{}])[0].get("price_source"),
        },
        "gate": {
            "passed": not findings,
            "findings": findings,
        },
        "provenance": {
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "license": SOURCE_LICENSE,
            "dataset_year": dataset_year,
            "extraction_date": datetime.now(timezone.utc).date().isoformat(),
            "record_id": record.get("source_fields", {}).get("record_id"),
        },
        "status": "proposed" if not findings else "rejected",
        "catalog_written": False,
        "requires_owner_approval": True,
    }
    return proposal


def run_validation(
    sample: Path,
    *,
    dataset_year: int,
    price_source: dict[str, Any] | None,
    output_dir: Path,
    with_taxes: bool,
) -> dict[str, Any]:
    if output_dir.resolve() != PROPOSALS_ROOT.resolve():
        raise ValueError("proposals may only be written under docs/data-sources/proposals")
    rows = read_rows(sample)
    taxes = None
    if with_taxes:
        manifest = yaml.safe_load((ROOT / "country-packs" / "AT" / "manifest.yaml").read_text(encoding="utf-8"))
        taxes = manifest.get("taxes", manifest)

    wltp_ok = is_wltp_era(dataset_year)
    records = [map_row(row, dataset_year, price_source) for row in rows]
    passed, rejected, reasons = 0, 0, Counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = 0

    for record in records:
        findings: list[str] = []
        if not wltp_ok:
            findings.append(NEDC_REJECTION)
        else:
            findings.extend(validate_variant_readiness(record, taxes))
        if findings:
            rejected += 1
            reasons.update(findings)
        else:
            passed += 1
        proposal = build_proposal(record, year=dataset_year, findings=findings, dataset_year=dataset_year)
        path = proposal_path(record, dataset_year)
        path.write_text(json.dumps(proposal, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        artifacts += 1

    return {
        "source": SOURCE_NAME,
        "sample_file": str(sample.relative_to(ROOT)),
        "dataset_year": dataset_year,
        "wltp_era": wltp_ok,
        "sampled": len(rows),
        "passed": passed,
        "rejected": rejected,
        "artifacts_written": artifacts,
        "artifact_dir": str(output_dir.relative_to(ROOT)),
        "coverage_percent": field_coverage(records),
        "rejection_reasons": dict(sorted(reasons.items())),
        "price_source_records": len(price_source or {}),
        "catalog_variants_written": 0,
    }


def load_price_source(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("price source must be a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default=str(ROOT / "docs" / "data-sources" / "sample" / "eea_at_2017_sample.tsv"))
    parser.add_argument("--dataset-year", type=int, default=2017)
    parser.add_argument("--price-source", default=None, help="optional JSON of attributed prices")
    parser.add_argument("--output-dir", default=str(PROPOSALS_ROOT))
    parser.add_argument("--no-taxes", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    sample_path = Path(args.sample)
    if not sample_path.is_absolute():
        sample_path = ROOT / sample_path
    report = run_validation(
        sample_path.resolve(),
        dataset_year=args.dataset_year,
        price_source=load_price_source(Path(args.price_source) if args.price_source else None),
        output_dir=Path(args.output_dir),
        with_taxes=not args.no_taxes,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"source: {report['source']} year={report['dataset_year']} wltp_era={report['wltp_era']}")
        print(f"sampled: {report['sampled']} passed: {report['passed']} rejected: {report['rejected']}")
        print(f"proposal artifacts: {report['artifacts_written']} -> {report['artifact_dir']}")
        print("coverage %:")
        for field, value in report["coverage_percent"].items():
            print(f"  {field}: {value}")
        print("rejection reasons:")
        for reason, count in report["rejection_reasons"].items():
            print(f"  {count}x {reason}")
        print("catalog/variants written: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
