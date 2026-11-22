"""Pilot price-tier contract and promotion guard.

This module is pure validation logic: no network access, no file writes, no
secret reads, and no catalog mutation. It is shared by the pilot staging runner
and the coverage scoreboard generator.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

PRICE_TIERS = (
    "verified",
    "derived",
    "approximate",
    "approximate_cross_market",
    "range",
    "unavailable",
)

# Tiers that must never be silently promoted to verified by an automated path.
PROMOTION_FORBIDDEN = frozenset({
    "approximate", "approximate_cross_market", "range", "unavailable",
})

USABLE_TIERS = frozenset({
    "verified", "derived", "approximate", "approximate_cross_market", "range",
})

VAT_BASIS = frozenset({"incl_vat", "excl_vat"})
CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})

# Research artifacts use these names; canonical staging/schema names take priority.
ALIASES = {
    "price_value": ("price_value", "price_value_eur"),
    "price_low": ("price_low", "price_low_eur"),
    "price_high": ("price_high", "price_high_eur"),
    "price_source_url": ("price_source_url", "source_url"),
    "price_source_date": ("price_source_date", "source_date"),
    "price_confidence": ("price_confidence", "confidence"),
    "price_adjustment_method": ("price_adjustment_method", "adjustment_method"),
}

PRICE_VALUE_FIELDS = ("price_value", "price_low", "price_high")


def field(record: dict[str, Any], canonical: str) -> Any:
    """Return the first present alias for a canonical field name."""
    for name in ALIASES.get(canonical, (canonical,)):
        if name in record:
            return record[name]
    return None


def validate_tier_transition(previous_tier: str | None, new_tier: str) -> list[str]:
    """Return errors for an inadmissible price-tier promotion."""
    errors: list[str] = []
    if new_tier not in PRICE_TIERS:
        errors.append(f"unknown price_tier '{new_tier}'")
        return errors
    if previous_tier is None:
        return errors
    if previous_tier not in PRICE_TIERS:
        errors.append(f"unknown previous price_tier '{previous_tier}'")
    elif previous_tier in PROMOTION_FORBIDDEN and new_tier == "verified":
        errors.append(
            f"promotion guard: {previous_tier} cannot be promoted to verified "
            "without a new owner-reviewed correction"
        )
    return errors


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def validate_price_fields(record: dict[str, Any], *, previous_tier: str | None = None) -> list[str]:
    """Validate a candidate record against the pilot price-tier contract.

    Returns a list of actionable errors; an empty list means the record is valid.
    """
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["candidate must be a JSON object"]

    tier = record.get("price_tier")
    if tier not in PRICE_TIERS:
        errors.append(f"unknown or missing price_tier: {tier!r}")
        return errors + validate_tier_transition(previous_tier, str(tier))

    errors.extend(validate_tier_transition(previous_tier, tier))

    values = {name: field(record, name) for name in PRICE_VALUE_FIELDS}
    for name, value in values.items():
        if value == 0:
            errors.append(f"{name} uses zero as a placeholder for an unknown price")
        elif value is not None and not _positive_number(value):
            errors.append(f"{name} must be a positive finite number or null")

    if tier == "unavailable":
        for name, value in values.items():
            if value is not None:
                errors.append(f"unavailable tier requires {name} to be null")
        return errors

    # Non-unavailable candidates require a positive price and complete provenance.
    if not _positive_number(values["price_value"]):
        errors.append("price_value must be a positive finite number")

    if tier == "range":
        for name in ("price_low", "price_high"):
            if not _positive_number(values[name]):
                errors.append(f"range tier requires a positive finite {name}")
        if all(_positive_number(values[n]) for n in ("price_low", "price_high")):
            if values["price_high"] < values["price_low"]:
                errors.append("price_high must be greater than or equal to price_low")

    if tier == "approximate_cross_market":
        for required in ("source_market", "fx_date", "fx_rate", "price_adjustment_method"):
            value = field(record, required)
            if value in (None, "", 0):
                errors.append(f"approximate_cross_market requires {required}")

    if tier == "derived" and not field(record, "derivation_method"):
        errors.append("derived tier requires a documented derivation_method")

    url = field(record, "price_source_url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        errors.append("price_source_url must be an http(s) URL")

    source_date = field(record, "price_source_date")
    if not isinstance(source_date, str) or len(source_date) < 8:
        errors.append("price_source_date must be an ISO date string")

    currency = record.get("currency")
    if not isinstance(currency, str) or len(currency) != 3:
        errors.append("currency must be a three-letter code")

    vat = record.get("vat_basis")
    if vat not in VAT_BASIS:
        errors.append(f"vat_basis must be one of {sorted(VAT_BASIS)}")

    confidence = field(record, "price_confidence")
    if confidence not in CONFIDENCE_LEVELS:
        errors.append(f"price_confidence must be one of {sorted(CONFIDENCE_LEVELS)}")

    if record.get("review_required") is not True:
        errors.append("review_required must be true for a non-unavailable price")

    return errors


def candidate_identity(record: dict[str, Any]) -> tuple[str, str, str | None, Any]:
    """Return the deduplication key components for a candidate."""
    return (
        str(record.get("brand") or ""),
        str(record.get("model") or ""),
        record.get("variant"),
        record.get("model_year"),
    )


def usable_price(record: dict[str, Any]) -> bool:
    return record.get("price_tier") in USABLE_TIERS
