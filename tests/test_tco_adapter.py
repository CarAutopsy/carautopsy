"""Tests for the offline TCO adapter."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tco_adapter as ta

FIX = ROOT / "tests/fixtures/tco_adapter/end_to_end.json"


def load():
    return json.loads(FIX.read_text(encoding="utf-8"))


def by_id(payload, variant_id):
    return next(r for r in payload["records"] if r["variant_id"] == variant_id)


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = ta.generate(FIX)

    def test_end_to_end_counts(self):
        self.assertEqual(self.payload["record_count"], 4)
        self.assertEqual(self.payload["accepted_count"], 1)
        self.assertEqual(self.payload["rejected_count"], 3)

    def test_successful_mapping_uses_only_supported_fields(self):
        record = by_id(self.payload, "fixture-tco-bev-accepted")
        self.assertTrue(record["accepted"])
        self.assertIsNotNone(record["tco_input"])
        allowed = {path for path, _, _, _ in ta.FIELD_MAP}
        self.assertTrue(set(record["mapped_fields"]).issubset(allowed))
        self.assertEqual(record["missing_mandatory_inputs"], [])
        self.assertEqual(record["validation_failures"], [])

    def test_missing_mandatory_input_rejects_record(self):
        record = by_id(self.payload, "fixture-tco-ice-missing-price")
        self.assertFalse(record["accepted"])
        self.assertIsNone(record["tco_input"])
        self.assertIn("offers.0.purchase_price_excl_vat_eur", record["missing_mandatory_inputs"])

    def test_approximate_value_is_labelled_not_promoted(self):
        record = by_id(self.payload, "fixture-tco-bev-accepted")
        self.assertIn("offers.0.purchase_price_excl_vat_eur", record["approximate_fields"])
        prov = next(p for p in record["provenance"]
                    if p["field"] == "offers.0.purchase_price_excl_vat_eur")
        self.assertEqual(prov["status"], "approximate")
        self.assertEqual(prov["price_tier"], "approximate")

    def test_unavailable_value_is_reported(self):
        record = by_id(self.payload, "fixture-tco-unavailable")
        self.assertIn("energy.consumption_wh_km.real_world", record["unavailable_fields"])
        self.assertFalse(record["accepted"])

    def test_invalid_provenance_requires_owner_decision(self):
        record = by_id(self.payload, "fixture-tco-owner-decision")
        self.assertIn("performance.electric_motor_continuous_power_w",
                      record["owner_decision_fields"])
        self.assertFalse(record["accepted"])
        self.assertIsNone(record["tco_input"])

    def test_rejection_paths_never_fabricate_defaults(self):
        for record in self.payload["records"]:
            if not record["accepted"]:
                self.assertIsNone(record["tco_input"])
                self.assertTrue(record["missing_mandatory_inputs"]
                                or record["owner_decision_fields"])

    def test_engine_is_never_invoked(self):
        for record in self.payload["records"]:
            self.assertFalse(record["tco_calculated"])
            self.assertFalse(record["engine_invoked"])
        self.assertEqual(self.payload["tco_calculations"], 0)
        self.assertFalse(self.payload["business_rules_changed"])

    def test_unsupported_powertrain_is_rejected(self):
        record = load()[0]
        record["identity"]["powertrain"] = "rocket"
        result = ta.adapt_record(record)
        self.assertFalse(result["accepted"])
        self.assertTrue(any("powertrain" in f for f in result["validation_failures"]))


class SafetyAndDeterminismTests(unittest.TestCase):
    def test_output_is_byte_stable(self):
        first = json.dumps(ta.generate(FIX), sort_keys=True)
        second = json.dumps(ta.generate(FIX), sort_keys=True)
        self.assertEqual(first, second)

    def test_no_timestamps(self):
        payload = ta.generate(FIX)
        self.assertNotIn("generated_at", payload)
        self.assertNotIn("retrieved_at", payload)

    def test_unsafe_report_paths_are_refused(self):
        for path in (ROOT / "catalog/x.json", ROOT / "catalog/variants/x.json", ROOT / "staging/x.json"):
            with self.subTest(path=path), self.assertRaises(ta.AdapterError) as ctx:
                ta.safe_report_path(path)
            self.assertEqual(ctx.exception.code, "UNSAFE_REPORT_PATH")

    def test_check_mode_writes_nothing(self):
        before = FIX.read_bytes()
        self.assertEqual(ta.main(["--check", "--input", str(FIX)]), 0)
        self.assertEqual(FIX.read_bytes(), before)

    def test_inputs_are_not_mutated(self):
        record = load()[0]
        snapshot = json.dumps(record, sort_keys=True)
        ta.adapt_record(record)
        self.assertEqual(json.dumps(record, sort_keys=True), snapshot)

    def test_no_writes_are_recorded(self):
        payload = ta.generate(FIX)
        for key in ("catalog_writes", "staging_writes", "provider_calls"):
            self.assertEqual(payload[key], 0)


if __name__ == "__main__":
    unittest.main()
