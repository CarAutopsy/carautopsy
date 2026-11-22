"""Tests for the read-only staging-input adapter."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import staging_input_adapter as adapter
import identity_conflicts

FIX = ROOT / "tests/fixtures/staging_input_adapter"
RAW = FIX / "raw"
INVALID = FIX / "invalid"


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = adapter.generate(RAW, expected_count=3)

    def test_variant_id_rule_is_filename_stem(self):
        self.assertEqual(adapter.variant_id_from_filename("001-fixture-alpha.json"),
                         "001-fixture-alpha")

    def test_expected_count_validation(self):
        self.assertEqual(adapter.validate_adapted_batch(self.payload["records"], expected_count=3), [])
        errors = adapter.validate_adapted_batch(self.payload["records"])
        self.assertTrue(any("exactly 48" in e for e in errors))

    def test_missing_brand_is_rejected(self):
        with self.assertRaises(adapter.AdapterError) as ctx:
            adapter.generate(INVALID, expected_count=1)
        self.assertIn("VALIDATION_FAILED", ctx.exception.code)

    def test_raw_record_is_preserved_exactly(self):
        source = json.loads((RAW / "001-fixture-alpha.json").read_text(encoding="utf-8"))
        record = next(r for r in self.payload["records"]
                      if r["variant_id"] == "001-fixture-alpha")
        self.assertEqual(record["raw"], source)

    def test_flat_fields_are_mapped_without_inference(self):
        record = next(r for r in self.payload["records"]
                      if r["variant_id"] == "001-fixture-alpha")
        self.assertEqual(record["identity"]["make"], "FixtureBrand")
        self.assertEqual(record["identity"]["model"], "FixtureAlpha")
        self.assertEqual(record["identity"]["variant"], "TrimA")
        self.assertEqual(record["specifications"]["battery_capacity_kwh"], 60.0)
        self.assertIsNone(record["specifications"]["battery_capacity_gross_kwh"]
                          if "battery_capacity_gross_kwh" in record["specifications"] else None)
        self.assertEqual(record["price"]["price_tier"], "approximate")

    def test_unavailable_price_stays_null(self):
        record = next(r for r in self.payload["records"]
                      if r["variant_id"] == "002-fixture-beta")
        self.assertEqual(record["price"]["price_tier"], "unavailable")
        self.assertIsNone(record["price"]["price_value"])

    def test_tool_input_strips_raw(self):
        tool_records = adapter.tool_input(self.payload)
        self.assertEqual(len(tool_records), 3)
        self.assertTrue(all("raw" not in r for r in tool_records))

    def test_downstream_tool_accepts_adapted_records(self):
        findings = identity_conflicts.detect(adapter.tool_input(self.payload))
        self.assertIsInstance(findings, list)
        for finding in findings:
            self.assertIn("owner_decision_required", finding)


class SafetyTests(unittest.TestCase):
    def test_output_is_deterministic_and_timestamp_free(self):
        first = json.dumps(adapter.generate(RAW, expected_count=3), sort_keys=True)
        second = json.dumps(adapter.generate(RAW, expected_count=3), sort_keys=True)
        self.assertEqual(first, second)
        self.assertNotIn("generated_at", first)
        self.assertNotIn("retrieved_at", first)

    def test_unsafe_output_paths_are_refused(self):
        for path in (ROOT / "catalog/x.json", ROOT / "catalog/variants/x.json", ROOT / "staging/x.json"):
            with self.subTest(path=path), self.assertRaises(adapter.AdapterError) as ctx:
                adapter.safe_report_path(path)
            self.assertEqual(ctx.exception.code, "UNSAFE_REPORT_PATH")

    def test_inputs_are_byte_identical_after_generation(self):
        before = {p.name: p.read_bytes() for p in RAW.glob("*.json")}
        adapter.generate(RAW, expected_count=3)
        after = {p.name: p.read_bytes() for p in RAW.glob("*.json")}
        self.assertEqual(before, after)

    def test_check_mode_writes_nothing(self):
        before = {p.name: p.read_bytes() for p in RAW.glob("*.json")}
        self.assertEqual(adapter.main(["--check", "--input-dir", str(RAW),
                                       "--expected-count", "3"]), 0)
        after = {p.name: p.read_bytes() for p in RAW.glob("*.json")}
        self.assertEqual(before, after)

    def test_zero_mutations(self):
        payload = adapter.generate(RAW, expected_count=3)
        for key in ("catalog_writes", "staging_writes", "provider_calls"):
            self.assertEqual(payload[key], 0)
        self.assertFalse(payload["source_records_modified"])


if __name__ == "__main__":
    unittest.main()
