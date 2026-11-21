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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_bulk_source import COLUMNS, FUEL_MAP, _number, _slug
from validate_tco_readiness import validate_variant_readiness

MIN_WLTP_YEAR = 2018
MAX_WLTP_YEAR = 2026
NEDC_REJECTION = "NEDC-only file, WLTP required"
SOURCE_NAME = "EEA type-approval CO2 microdata"
SOURCE_URL = "https://www.eea.europa.eu/data-and-maps/data/co2-cars-emission-20"
SOURCE_LICENSE = "CC BY 4.0"
DERIVED_FROM = "co2_nedc_wltp"
CO2_DIVISOR = {"ice_petrol": 23.2, "ice_diesel": 26.5}
PROPOSALS_ROOT = ROOT / "docs" / "data-sources" / "proposals"
DEFAULT_STATUTORY_RULES = ROOT / "docs" / "data-sources" / "statutory" / "at-rules-v1.json"
STATUTORY_FIELDS = ("statutory.nova.verified", "statutory.motor_tax.verified")
IDENTITY_QUALITY_OK = "ok"
IDENTITY_QUALITY_CURATION = "requires_manual_curation"
# A short uppercase letter code followed by digits (e.g. "A02") or a
# type-approval signature (e.g. "E1*2001/116*...") is not a consumer-facing
# model identity. Deliberately conservative: descriptive names with spaces or
# mixed case are not matched.
NON_DESCRIPTIVE_VARIANT_RE = re.compile(
    r"^(?:[A-Z]{1,3}\d{1,4}|[A-Za-z0-9]{1,5}[*/][A-Za-z0-9*/]+)$"
)
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
    *STATUTORY_FIELDS,
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


def load_statutory_rules(path: Path = DEFAULT_STATUTORY_RULES) -> dict[str, Any]:
    """Load versioned, attributed statutory rules; fail closed on bad metadata."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("jurisdiction") != "AT":
        raise ValueError("statutory rules must be version 1 for AT")
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("statutory rules file has no rules")
    required = (
        "id", "tax", "powertrain", "applicable_from", "applicable_to", "exemption",
        "legal_basis", "source_url", "publisher", "retrieved",
    )
    for rule in rules:
        if not isinstance(rule, dict) or any(field not in rule for field in required):
            raise ValueError("statutory rule is missing required provenance metadata")
        date.fromisoformat(rule["applicable_from"])
        if rule["applicable_to"] is not None:
            date.fromisoformat(rule["applicable_to"])
    return data


def _powertrain_group(powertrain: str | None) -> str:
    return "bev" if powertrain == "bev" else "non_electric"


def _rule_in_period(rule: dict[str, Any], day: date) -> bool:
    start = date.fromisoformat(rule["applicable_from"])
    end = date.fromisoformat(rule["applicable_to"]) if rule["applicable_to"] is not None else None
    return start <= day and (end is None or day <= end)


def evaluate_statutory(
    record: dict[str, Any],
    rules: dict[str, Any],
    day: date,
) -> dict[str, Any]:
    """Resolve in-period rules for both taxes and derive readiness tax inputs.

    An exemption is a verified legal outcome (exemption=true, rate=0); it is not
    an invented rate. Missing or out-of-period rules always fail closed.
    """
    powertrain = record.get("source_fields", {}).get("powertrain")
    group = _powertrain_group(powertrain)
    co2 = record.get("source_fields", {}).get("co2_g_per_km")
    findings: list[str] = []

    selected: dict[str, dict[str, Any]] = {}
    for tax in ("nova", "motorbezogene_versicherungssteuer"):
        candidates = [
            rule for rule in rules["rules"]
            if rule.get("tax") == tax and rule.get("powertrain") == group
        ]
        in_period = [rule for rule in candidates if _rule_in_period(rule, day)]
        if len(in_period) != 1:
            findings.append(
                f"STATUTORY_RULE_UNAVAILABLE: {tax} for {group} on {day.isoformat()} "
                f"(matched {len(in_period)} rules)"
            )
            continue
        selected[tax] = in_period[0]

    nova_rule = selected.get("nova")
    if nova_rule is not None and nova_rule.get("exemption") is True:
        eligible = isinstance(co2, (int, float)) and co2 == 0
        if not eligible:
            findings.append("NOVA_EXEMPTION_NOT_ELIGIBLE: zero-CO2 electric vehicle required")

    if findings:
        return {
            "nova": {"verified": False, "exemption": None, "rate_eur": None},
            "motor_tax": {"verified": False, "exemption": None, "rate_eur_per_month": None},
            "taxes": None,
            "verified": False,
            "findings": findings,
        }

    nova = {"exemptions": [], "annual_rules": {}}
    nova_result: dict[str, Any] = {"verified": True, "exemption": bool(nova_rule["exemption"])}
    if nova_rule["exemption"]:
        nova["exemptions"] = ["bev", "fcev"]
        nova_result["rate_eur"] = nova_rule["rate_eur"]
        nova_result["outcome"] = "verified statutory exemption"
        nova_result["legal_basis"] = nova_rule["legal_basis"]
        nova_result["source_url"] = nova_rule["source_url"]
    else:
        formula = nova_rule["formula"]
        nova["annual_rules"] = {day.year: {
            "co2_deduction_gkm": formula["co2_deduction_gkm"],
            "divisor": formula["divisor"],
            "min_percentage": formula["min_percentage"],
            "max_percentage": formula["max_percentage"],
            "rounding": formula["rounding"],
            "malus_threshold_gkm": formula["malus_threshold_gkm"],
            "malus_eur_per_gkm": formula["malus_eur_per_gkm"],
            "fixed_deduction_eur": formula["fixed_deduction_eur"],
        }}
        nova_result["rate_eur"] = None
        nova_result["outcome"] = "verified formula-based rate"
        nova_result["legal_basis"] = nova_rule["legal_basis"]
        nova_result["source_url"] = nova_rule["source_url"]

    motor_rule = selected["motorbezogene_versicherungssteuer"]
    motor: dict[str, Any] = {"annual_rules": {}}
    motor_result: dict[str, Any] = {"verified": True, "exemption": bool(motor_rule["exemption"])}
    if motor_rule["exemption"]:
        motor["bev_m1"] = {
            "exemption": True,
            "rate_eur_per_month": motor_rule["rate_eur_per_month"],
            "legal_basis": motor_rule["legal_basis"],
            "source_url": motor_rule["source_url"],
        }
        motor_result["rate_eur_per_month"] = motor_rule["rate_eur_per_month"]
        motor_result["outcome"] = "verified statutory exemption"
        motor_result["legal_basis"] = motor_rule["legal_basis"]
        motor_result["source_url"] = motor_rule["source_url"]
    else:
        formula = motor_rule["formula"]
        schedule = {
            "power_tiers_eur_per_kw": formula["power_tiers_eur_per_kw"],
            "minimum_taxable_kw": 5,
            "minimum_tax_eur": formula["minimum_eur_per_month"],
            "rate_eur": 0.72,
        }
        motor["annual_rules"] = {day.year: {"ice": schedule, "phev": schedule}}
        motor_result["rate_eur_per_month"] = None
        motor_result["outcome"] = "verified non-electric M1 schedule"
        motor_result["legal_basis"] = motor_rule["legal_basis"]
        motor_result["source_url"] = motor_rule["source_url"]

    return {
        "nova": nova_result,
        "motor_tax": motor_result,
        "taxes": {"nova": nova, "motorbezogene_versicherungssteuer": motor},
        "verified": True,
        "findings": [],
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
    derived = derive_fuel_consumption(co2, powertrain)
    if derived is not None:
        derived["co2_basis"] = co2_basis
    price = attach_price(variant_id, price_source)

    power_kw = _number(row.get("ep (KW)", ""))
    mass_kg = _number(row.get("m (kg)", ""))
    own_weight_kg = _number(row.get("Mt", ""))
    electric_wh_km = _number(row.get("z (Wh/km)", ""))
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
    dimensions: dict[str, Any] = {}
    if mass_kg is not None:
        dimensions["max_permissible_mass_kg"] = mass_kg
    if own_weight_kg is not None:
        dimensions["own_weight_kg"] = own_weight_kg
    if dimensions:
        result["dimensions"] = dimensions
    if electric_wh_km is not None:
        result["energy"] = {"consumption_wh_km": {"wltp_combined": electric_wh_km}}
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
    if path in STATUTORY_FIELDS:
        _, section, field = path.split(".", 2)
        statutory = record.get("statutory")
        return isinstance(statutory, dict) and isinstance(statutory.get(section), dict) and (
            statutory[section].get(field) is True
        )
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


def evaluate_identity_quality(record: dict[str, Any]) -> dict[str, Any]:
    """Conservatively assess whether the EEA identity is consumer-facing.

    This is a pre-ingestion curation marker, not a hard data-readiness gate. It
    never invents or guesses a model name, trim, market name or specification:
    when the source identity cannot be verified, the proposal is marked for
    manual curation with an explicit reason.
    """
    identity = record.get("identity") or {}
    make = str(identity.get("make") or "").strip()
    model = str(identity.get("model") or "").strip()
    variant = str(identity.get("variant_name") or "").strip()
    reasons: list[str] = []

    if not make:
        reasons.append("make is missing")
    if not model:
        reasons.append("model is missing")
    elif model.casefold() == make.casefold():
        reasons.append(
            f"model equals make ('{model}'); no distinct commercial model identity"
        )
    if not variant:
        reasons.append("variant_name is missing")
    elif NON_DESCRIPTIVE_VARIANT_RE.fullmatch(variant):
        reasons.append(
            f"variant_name '{variant}' is a non-descriptive approval/type code; "
            "no documented commercial model identity supplied"
        )

    requires_curation = bool(reasons)
    curation_reason = None
    if requires_curation:
        curation_reason = (
            f"EEA source provides make='{make}', model='{model}', variant='{variant}', "
            "which does not establish a consumer-facing vehicle identity: "
            + "; ".join(reasons)
            + ". No commercial model name, trim, market name or specification was "
            "invented; a human curator must verify the identity before ingestion."
        )
    return {
        "identity_quality": (
            IDENTITY_QUALITY_CURATION if requires_curation else IDENTITY_QUALITY_OK
        ),
        "curation_reason": curation_reason,
        "reasons": reasons,
    }


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
    identity_quality = evaluate_identity_quality(record)
    proposal: dict[str, Any] = {
        "schema_version": 1,
        "identity_quality": identity_quality["identity_quality"],
        "curation_reason": identity_quality["curation_reason"],
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
        "statutory": record.get("statutory", {}),
        "provenance": {
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "license": SOURCE_LICENSE,
            "dataset_year": dataset_year,
            "extraction_date": datetime.now(UTC).date().isoformat(),
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
    include_rejected: bool = False,
) -> dict[str, Any]:
    if output_dir.resolve() != PROPOSALS_ROOT.resolve():
        raise ValueError("proposals may only be written under docs/data-sources/proposals")
    rows = read_rows(sample)
    statutory_rules = load_statutory_rules() if with_taxes else None

    wltp_ok = is_wltp_era(dataset_year)
    records = [map_row(row, dataset_year, price_source) for row in rows]
    passed, rejected, reasons = 0, 0, Counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = 0
    curation_required = 0

    for record in records:
        findings: list[str] = []
        if statutory_rules is None:
            statutory = {
                "nova": {"verified": False, "exemption": None, "rate_eur": None},
                "motor_tax": {"verified": False, "exemption": None, "rate_eur_per_month": None},
                "verified": False,
                "findings": ["STATUTORY_RULES_NOT_APPLIED: --no-taxes"],
            }
        else:
            registered = date.fromisoformat(record["registration"]["first_registration_date"])
            statutory = evaluate_statutory(record, statutory_rules, registered)
            findings.extend(statutory["findings"])
        record["statutory"] = statutory
        if not wltp_ok:
            findings.append(NEDC_REJECTION)
        elif statutory["verified"]:
            findings.extend(validate_variant_readiness(record, statutory["taxes"]))
        if findings:
            rejected += 1
            reasons.update(findings)
        else:
            passed += 1
        if findings and not include_rejected:
            continue
        proposal = build_proposal(record, year=dataset_year, findings=findings, dataset_year=dataset_year)
        path = proposal_path(record, dataset_year)
        # Owner-approved dedup flags live in the artifacts; never silently drop
        # them when regenerating a proposal from source evidence.
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            for field in ("duplicate_of", "deduplication_role"):
                if field in previous:
                    proposal[field] = previous[field]
        path.write_text(json.dumps(proposal, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        artifacts += 1
        if proposal["identity_quality"] == IDENTITY_QUALITY_CURATION:
            curation_required += 1

    return {
        "source": SOURCE_NAME,
        "sample_file": str(sample.relative_to(ROOT)),
        "dataset_year": dataset_year,
        "wltp_era": wltp_ok,
        "sampled": len(rows),
        "passed": passed,
        "rejected": rejected,
        "artifacts_written": artifacts,
        "artifact_dir": str(output_dir.relative_to(ROOT)) if output_dir.is_relative_to(ROOT) else str(output_dir),
        "coverage_percent": field_coverage(records),
        "rejection_reasons": dict(sorted(reasons.items())),
        "price_source_records": len(price_source or {}),
        "identity_curation_required_count": curation_required,
        "statutory_rules_applied": statutory_rules is not None,
        "statutory_verified_count": sum(
            1 for record in records if record.get("statutory", {}).get("verified") is True
        ),
        "catalog_variants_written": 0,
    }


def load_price_source(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("price source must be a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default=str(ROOT / "docs" / "data-sources" / "sample" / "eea_at_2017_sample.tsv"))
    parser.add_argument("--dataset-year", type=int, default=2017)
    parser.add_argument("--price-source", default=None, help="optional JSON of attributed prices")
    parser.add_argument("--output-dir", default=str(PROPOSALS_ROOT))
    parser.add_argument("--no-taxes", action="store_true")
    parser.add_argument("--include-rejected", action="store_true", help="write artifacts for rejected records too")
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
        include_rejected=args.include_rejected,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"source: {report['source']} year={report['dataset_year']} wltp_era={report['wltp_era']}")
        print(f"sampled: {report['sampled']} passed: {report['passed']} rejected: {report['rejected']}")
        print(f"proposal artifacts: {report['artifacts_written']} -> {report['artifact_dir']}")
        print(f"identity requires_manual_curation: {report['identity_curation_required_count']}")
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
