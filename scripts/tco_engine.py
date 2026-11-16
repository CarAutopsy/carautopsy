"""Shared Austrian TCO engine with fail-closed, year-aware M1 tax calculations."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import math
import re
from pathlib import Path
import yaml

_ENGINE_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "tco-contract.json"
_ENGINE_CONTRACT = json.loads(_ENGINE_CONTRACT_PATH.read_text(encoding="utf-8"))
ENGINE_VERSION = _ENGINE_CONTRACT.get("engine_version")
if not isinstance(ENGINE_VERSION, str) or not ENGINE_VERSION.strip():
    raise ValueError("TCO engine contract is missing a valid engine_version")


def publication_metadata(taxes):
    """Return the engine and tax-pack identity embedded in every published artifact."""
    version = taxes.get("version") if isinstance(taxes, dict) else None
    status = taxes.get("status") if isinstance(taxes, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Cannot publish TCO metadata without a country-pack version")
    if status not in {"draft", "verified"}:
        raise ValueError("Cannot publish TCO metadata without a recognized country-pack status")
    return {
        "engine_version": ENGINE_VERSION,
        "country_pack": f"AT@{version}",
        "country_pack_status": status,
    }



def publication_artifact_is_current(existing, candidate, now=None):
    """Return True only when the stored artifact is identical and still fresh."""
    if not isinstance(existing, dict) or not isinstance(candidate, dict):
        return False
    if existing.get("results") != candidate.get("results"):
        return False
    if existing.get("summary") != candidate.get("summary"):
        return False

    old_envelope = existing.get("envelope")
    new_envelope = candidate.get("envelope")
    if not isinstance(old_envelope, dict) or not isinstance(new_envelope, dict):
        return False
    stable_old = {key: value for key, value in old_envelope.items() if key != "generated_utc"}
    stable_new = {key: value for key, value in new_envelope.items() if key != "generated_utc"}
    if stable_old != stable_new:
        return False

    generated = old_envelope.get("generated_utc")
    if (
        not isinstance(generated, str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
            generated,
        ) is None
    ):
        return False
    try:
        generated_at = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError:
        return False
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        return False

    max_age_days = _ENGINE_CONTRACT.get("max_artifact_age_days")
    future_skew_minutes = _ENGINE_CONTRACT.get("max_future_skew_minutes")
    if (
        isinstance(max_age_days, bool) or not isinstance(max_age_days, (int, float))
        or not math.isfinite(max_age_days) or max_age_days <= 0
        or isinstance(future_skew_minutes, bool) or not isinstance(future_skew_minutes, (int, float))
        or not math.isfinite(future_skew_minutes) or future_skew_minutes < 0
    ):
        return False

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("Artifact freshness comparison requires a timezone-aware clock")
    age_seconds = (current_time - generated_at).total_seconds()
    return (
        age_seconds <= max_age_days * 86400
        and age_seconds >= -future_skew_minutes * 60
    )


def load_country_config(root):
    root = Path(root)
    def read(name):
        with (root / f"country-packs/AT/{name}.yaml").open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    taxes, defaults, inspections = read("taxes"), read("defaults"), read("inspections")
    validate_config(defaults, inspections)
    return taxes, defaults, inspections


def validate_config(d, i):
    paths = (
        "horizon_years_default", "annual_km_default", "tyres.replacement_interval_km",
        "tyres.average_cost_eur", "maintenance.bev_annual_eur", "maintenance.ice_annual_eur",
        "insurance_proxy.bev_annual_eur", "insurance_proxy.ice_annual_eur",
        "electricity.default_tariff_eur_kwh", "fuel.petrol_eur_l", "fuel.diesel_eur_l",
    )
    for path in paths:
        value = d
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Invalid or missing Austria TCO config: {path}")
    for path in ("horizon_years_default", "annual_km_default", "tyres.replacement_interval_km"):
        value = d
        for key in path.split("."):
            value = value[key]
        if value <= 0:
            raise ValueError(f"Austria TCO config must be greater than zero: {path}")
    cost = (i.get("defaults") or {}).get("average_cost_eur")
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
        raise ValueError("Invalid or missing Austria inspection config: defaults.average_cost_eur")


FUEL_CONSUMPTION_DEFAULT = {"ice_diesel": 6.5, "ice_petrol": 6.0, "hev": 4.5, "phev": 5.0}


def _is_finite_number(value):
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def _required(mapping, path, label):
    value = mapping
    for key in path.split("."):
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            value = None
    if value is None or isinstance(value, bool):
        raise ValueError(f"Cannot calculate Austrian tax: missing {label}")
    return value


def _first_registration_year(v):
    raw = _required(v, "registration.first_registration_date", "registration.first_registration_date")
    try:
        parsed = date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        raise ValueError("Cannot calculate Austrian tax: invalid registration.first_registration_date") from None
    return parsed.year, parsed


def _round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _tiered(amount, tiers, upper_key, rate_key):
    remaining = max(0.0, float(amount))
    total = 0.0
    lower = 0.0
    for tier in tiers:
        upper = tier.get(upper_key)
        rate = float(tier[rate_key])
        if upper is None:
            total += remaining * rate
            remaining = 0
            break
        width = max(0.0, float(upper) - lower)
        applied = min(remaining, width)
        total += applied * rate
        remaining -= applied
        lower = float(upper)
    if remaining > 0:
        raise ValueError("Tax tier schedule does not cover the taxable amount")
    return total


def nova(v, t):
    """One-time M1 NoVA; price must be explicitly VAT-exclusive and NoVA-exclusive."""
    pt = _required(v, "identity.powertrain", "identity.powertrain")
    rules = t.get("nova", {})
    if pt in rules.get("exemptions", []):
        return 0.0
    vehicle_class = _required(v, "identity.vehicle_class", "identity.vehicle_class")
    if vehicle_class != "M1":
        raise ValueError(f"NoVA calculation unsupported for vehicle class {vehicle_class}")
    year, _ = _first_registration_year(v)
    if year == 2025 and _first_registration_year(v)[1] < date(2025, 7, 1):
        raise ValueError("NoVA rules unavailable before 2025-07-01")
    schedule = rules.get("annual_rules", {}).get(year)
    if not schedule:
        raise ValueError(f"NoVA rules unavailable for first-registration year {year}")
    co2_path = "emissions.co2_wltp_weighted_combined_gpkm" if pt == "phev" else "emissions.co2_wltp_gpkm"
    co2 = float(_required(v, co2_path, co2_path))
    base = float(_required(v, "offers.0.purchase_price_excl_vat_eur", "offers[0].purchase_price_excl_vat_eur"))
    if base <= 0 or co2 < 0:
        raise ValueError("Cannot calculate NoVA: price and CO2 must be positive/non-negative")
    rate = _round_half_up((co2 - float(schedule["co2_deduction_gkm"])) / float(schedule["divisor"]))
    rate = max(int(schedule.get("min_percentage", 0)), min(int(schedule["max_percentage"]), rate))
    malus = max(0.0, co2 - float(schedule["malus_threshold_gkm"])) * float(schedule["malus_eur_per_gkm"])
    return round(max(0.0, base * rate / 100.0 + malus - float(schedule["fixed_deduction_eur"])), 2)


def motor_monthly(v, t):
    """M1 monthly motorbezogene Versicherungssteuer, selected by first-registration date."""
    pt = _required(v, "identity.powertrain", "identity.powertrain")
    vehicle_class = _required(v, "identity.vehicle_class", "identity.vehicle_class")
    if vehicle_class != "M1":
        raise ValueError(f"Motorbezogene Versicherungssteuer unsupported for vehicle class {vehicle_class}")
    year, first_date = _first_registration_year(v)
    max_mass = float(_required(v, "dimensions.max_permissible_mass_kg", "dimensions.max_permissible_mass_kg"))
    if max_mass > 3500:
        raise ValueError("Motorbezogene Versicherungssteuer M1 calculation supports only vehicles up to 3,500 kg")
    rules = t.get("motorbezogene_versicherungssteuer", {})
    if pt == "bev":
        spec = rules["bev_m1"]
        power_kw = float(_required(v, "performance.electric_motor_continuous_power_w", "performance.electric_motor_continuous_power_w")) / 1000
        weight_kg = float(_required(v, "dimensions.own_weight_kg", "dimensions.own_weight_kg"))
        if power_kw < 0 or weight_kg < 0:
            raise ValueError("BEV tax inputs must be non-negative")
        power_taxable = max(float(spec["power"]["minimum_taxable_kw"]), power_kw - float(spec["power"]["deduction_kw"]))
        weight_taxable = max(float(spec["weight"]["minimum_taxable_kg"]), weight_kg - float(spec["weight"]["deduction_kg"]))
        return round(
            _tiered(power_taxable, spec["power"]["tiers"], "up_to_kw", "rate_eur_per_kw") +
            _tiered(weight_taxable, spec["weight"]["tiers"], "up_to_kg", "rate_eur_per_kg"), 2
        )
    if pt in ("ice_petrol", "ice_diesel", "hev", "phev"):
        kind = "phev" if pt == "phev" else "ice"
        schedule = rules.get("annual_rules", {}).get(year, {}).get(kind)
        if not schedule:
            raise ValueError(f"Motor-tax {kind.upper()} rules unavailable for first-registration year {year}")
        power_kw = float(_required(v, "performance.combustion_engine_power_w", "performance.combustion_engine_power_w")) / 1000
        co2_path = "emissions.co2_wltp_weighted_combined_gpkm" if kind == "phev" else "emissions.co2_wltp_gpkm"
        co2 = float(_required(v, co2_path, co2_path))
        taxable_kw = max(float(schedule["minimum_taxable_kw"]), power_kw - float(schedule["power_deduction_kw"]))
        taxable_co2 = max(float(schedule["minimum_taxable_gpkm"]), co2 - float(schedule["co2_deduction_gpkm"]))
        return round((taxable_kw + taxable_co2) * float(schedule["rate_eur"]), 2)
    raise ValueError(f"Motor-tax rules unsupported for powertrain {pt!r}; refusing zero-tax fallback")


def assert_tax_pack_publishable(taxes):
    """Require explicit statutory verification before any production publication."""
    status = taxes.get("status")
    if status != "verified":
        raise ValueError(f"Austria tax pack status is {status!r}; publication requires status 'verified'")
    if not taxes.get("nova", {}).get("annual_rules"):
        raise ValueError("Austria NoVA annual_rules are missing; publication refused")
    motor = taxes.get("motorbezogene_versicherungssteuer", {})
    if not motor.get("bev_m1") or not motor.get("annual_rules"):
        raise ValueError("Austria motor-tax schedules are incomplete; publication refused")


def calculate_tco(v, t, d, i, allow_draft=False):
    if t.get("status") == "draft" and not allow_draft:
        raise ValueError("Austria tax pack is draft; TCO publication is disabled pending legal verification")
    identity = v.get("identity") or {}
    pt = identity.get("powertrain")
    if not pt:
        return None
    years, km = d["horizon_years_default"], d["annual_km_default"]
    n = nova(v, t)
    monthly_tax = motor_monthly(v, t)
    mt = monthly_tax * 12 * years
    if pt == "bev":
        cons = (v.get("energy") or {}).get("consumption_wh_km") or {}
        raw_consumption = cons.get("real_world") or cons.get("wltp_combined")
        if (isinstance(raw_consumption, bool) or
                not isinstance(raw_consumption, (int, float)) or
                not _is_finite_number(raw_consumption) or raw_consumption <= 0):
            raise ValueError("Cannot calculate TCO: finite positive BEV consumption is required")
        wh = float(raw_consumption)
        energy = wh / 1000 * km * d["electricity"]["default_tariff_eur_kwh"] * years
    else:
        cons = ((v.get("extensions") or {}).get("fuel_consumption_l_100km") or {})
        raw_consumption = cons.get("real_world") or cons.get("wltp_combined")
        if (isinstance(raw_consumption, bool) or
                not isinstance(raw_consumption, (int, float)) or
                not math.isfinite(raw_consumption) or raw_consumption <= 0):
            raise ValueError("Cannot calculate TCO: finite positive fuel consumption is required")
        l100 = float(raw_consumption)
        energy = l100 / 100 * km * d["fuel"]["diesel_eur_l" if pt == "ice_diesel" else "petrol_eur_l"] * years
    key = "bev_annual_eur" if pt == "bev" else "ice_annual_eur"
    maint = d["maintenance"][key] * years
    insurance = d["insurance_proxy"][key] * years
    tyre = d["tyres"]
    tyres = km * years / tyre["replacement_interval_km"] * tyre["average_cost_eur"]
    inspection = i["defaults"]["average_cost_eur"] * years
    total = n + mt + energy + maint + insurance + tyres + inspection
    offers = v.get("offers") or []
    return {
        "variant_id": v.get("variant_id"), "make": identity.get("make"), "model": identity.get("model"),
        "variant_name": identity.get("variant_name"), "powertrain": pt,
        "power_kw": round((v.get("performance", {}).get("power_w") or 0) / 1000, 1),
        "co2_gkm": v.get("emissions", {}).get("co2_wltp_gpkm"),
        "list_price_eur": round((offers[0].get("list_price_minor") or 0) / 100, 2) if offers else None,
        "nova_eur": n, "motor_tax_monthly_eur": monthly_tax,
        "energy_5y_eur": round(energy, 2), "maintenance_5y_eur": round(maint, 2),
        "insurance_5y_eur": round(insurance, 2), "tyres_5y_eur": round(tyres, 2),
        "inspection_5y_eur": round(inspection, 2), "total_5y_eur": round(total, 2),
        "monthly_eur": round(total / (years * 12), 2),
        "data_confidence": (v.get("provenance") or {}).get("confidence"),
    }
