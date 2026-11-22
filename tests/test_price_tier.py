"""Tests for the pilot price-tier contract and promotion guard."""
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import price_tier


def valid_record(**overrides):
    record = {
        "brand": "Volkswagen",
        "model": "Golf",
        "variant": "Trend",
        "price_tier": "approximate",
        "price_value": 26790.0,
        "currency": "EUR",
        "vat_basis": "incl_vat",
        "price_source_url": "https://www.volkswagen.at/golf/golf",
        "price_source_date": "2026-11-22",
        "price_confidence": "medium",
        "review_required": True,
    }
    record.update(overrides)
    return record


class PriceTierTests(unittest.TestCase):
    def test_all_six_tiers_are_allowed(self):
        self.assertEqual(len(price_tier.PRICE_TIERS), 6)
        for tier in price_tier.PRICE_TIERS:
            with self.subTest(tier=tier):
                errors = price_tier.validate_price_fields(valid_record(price_tier=tier))
                self.assertIsInstance(errors, list)
                self.assertFalse(any("unknown price_tier" in e for e in errors))

    def test_unknown_tier_is_rejected(self):
        errors = price_tier.validate_price_fields(valid_record(price_tier="invented"))
        self.assertTrue(any("unknown" in e for e in errors))

    def test_promotion_guard_blocks_all_non_verified_tiers(self):
        for tier in ("approximate", "approximate_cross_market", "range", "unavailable"):
            with self.subTest(tier=tier):
                errors = price_tier.validate_tier_transition(tier, "verified")
                self.assertTrue(any("promotion guard" in e for e in errors))

    def test_same_tier_and_downgrade_are_allowed(self):
        self.assertEqual(price_tier.validate_tier_transition("approximate", "approximate"), [])
        self.assertEqual(price_tier.validate_tier_transition("verified", "unavailable"), [])

    def test_unavailable_requires_null_prices(self):
        record = valid_record(price_tier="unavailable", price_value=None)
        self.assertEqual(price_tier.validate_price_fields(record), [])
        bad = valid_record(price_tier="unavailable")
        errors = price_tier.validate_price_fields(bad)
        self.assertTrue(any("unavailable tier" in e for e in errors))

    def test_zero_placeholder_is_rejected(self):
        errors = price_tier.validate_price_fields(valid_record(price_value=0))
        self.assertTrue(any("zero as a placeholder" in e for e in errors))

    def test_missing_provenance_is_rejected(self):
        record = valid_record()
        for key in ("price_source_url", "price_source_date", "currency", "vat_basis",
                    "price_confidence", "review_required"):
            record.pop(key, None)
        errors = price_tier.validate_price_fields(record)
        self.assertTrue(any("price_source_url" in e for e in errors))
        self.assertTrue(any("vat_basis" in e for e in errors))
        self.assertTrue(any("review_required" in e for e in errors))

    def test_range_requires_low_and_high(self):
        errors = price_tier.validate_price_fields(valid_record(price_tier="range"))
        self.assertTrue(any("range tier" in e for e in errors))

    def test_cross_market_requires_fx_provenance(self):
        errors = price_tier.validate_price_fields(valid_record(price_tier="approximate_cross_market"))
        for field in ("source_market", "fx_date", "fx_rate", "price_adjustment_method"):
            self.assertTrue(any(field in e for e in errors), field)

    def test_derived_requires_derivation_method(self):
        errors = price_tier.validate_price_fields(valid_record(price_tier="derived"))
        self.assertTrue(any("derivation_method" in e for e in errors))

    def test_research_field_aliases_are_accepted(self):
        record = {
            "brand": "Škoda", "model": "Octavia", "price_tier": "approximate",
            "price_value_eur": 22630.0, "source_url": "https://www.skoda.at/x",
            "source_date": "2018-11-30", "confidence": "low",
            "currency": "EUR", "vat_basis": "incl_vat", "review_required": True,
        }
        self.assertEqual(price_tier.validate_price_fields(record), [])
        self.assertEqual(price_tier.field(record, "price_value"), 22630.0)

    def test_candidate_identity_and_usable_price(self):
        record = valid_record()
        self.assertEqual(price_tier.candidate_identity(record)[:2], ("Volkswagen", "Golf"))
        self.assertTrue(price_tier.usable_price(record))
        self.assertFalse(price_tier.usable_price(valid_record(price_tier="unavailable")))


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads((ROOT / "schemas/vehicle-variant.schema.json").read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        cls.validator = Draft7Validator(schema)

    def test_new_price_fields_are_in_schema(self):
        props = self.validator.schema["properties"]
        for name in ("price_tier", "price_confidence", "price_source_date",
                     "price_adjustment_method", "vat_basis", "review_required"):
            self.assertIn(name, props)

    def test_schema_accepts_valid_price_tier(self):
        record = {
            "schema_version": "1.0.0", "variant_id": "test-price-tier", "status": "proposed",
            "identity": {"make": "VW"}, "provenance": {"confidence": "low"},
            "price_tier": "approximate", "vat_basis": "incl_vat", "review_required": True,
        }
        self.assertEqual(list(self.validator.iter_errors(record)), [])

    def test_schema_rejects_unknown_tier_and_vat(self):
        base = {
            "schema_version": "1.0.0", "variant_id": "test-price-tier", "status": "proposed",
            "identity": {"make": "VW"}, "provenance": {"confidence": "low"},
        }
        self.assertTrue(list(self.validator.iter_errors(dict(base, price_tier="invented"))))
        self.assertTrue(list(self.validator.iter_errors(dict(base, vat_basis="unknown"))))


if __name__ == "__main__":
    unittest.main()
