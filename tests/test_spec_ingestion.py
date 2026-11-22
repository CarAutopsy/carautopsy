"""Tests for the offline vehicle-specification ingestion pipeline."""
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import spec_ingestion as si

FIX = ROOT / "tests/fixtures/spec_ingestion"
SCHEMA = ROOT / "schemas/vehicle-specification.schema.json"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class ValidationTests(unittest.TestCase):
    def test_complete_fixture_has_no_errors(self):
        for record in load("complete.json"):
            self.assertEqual(si.validate_observation(record), [])

    def test_partial_fixture_has_no_errors(self):
        for record in load("partial.json"):
            self.assertEqual(si.validate_observation(record), [])

    def test_missing_mandatory_identity_is_rejected(self):
        record = load("invalid.json")[0]
        errors = si.validate_observation(record)
        self.assertTrue(any("identity.model" in e for e in errors))
        self.assertTrue(any("model_year" in e for e in errors))

    def test_date_format_is_validated(self):
        errors = si.validate_observation(load("invalid.json")[0])
        self.assertTrue(any("retrieval_date" in e for e in errors))

    def test_units_and_bounds_are_validated(self):
        errors = si.validate_observation(load("invalid.json")[0])
        self.assertTrue(any("battery_capacity_kwh" in e for e in errors))
        self.assertTrue(any("electric_range_km" in e for e in errors))
        self.assertTrue(any("dimensions.length_mm" in e for e in errors))

    def test_enum_values_are_validated(self):
        errors = si.validate_observation(load("invalid.json")[0])
        self.assertTrue(any("body_style" in e for e in errors))
        self.assertTrue(any("source_type" in e for e in errors))
        self.assertTrue(any("confidence" in e for e in errors))

    def test_unsupported_provenance_is_rejected(self):
        errors = si.validate_observation(load("invalid.json")[0])
        for fragment in ("source_url", "retrieval_date", "source_type", "license_attribution_status"):
            self.assertTrue(any(fragment in e for e in errors), fragment)


class PipelineTests(unittest.TestCase):
    def test_complete_and_partial_counts(self):
        payload = si.generate(FIX / "complete.json")
        self.assertEqual(payload["accepted_count"], 2)
        self.assertEqual(payload["rejected_count"], 0)
        statuses = {r["evidence_status"] for r in payload["records"]}
        self.assertIn("complete", statuses)

    def test_partial_record_keeps_nulls(self):
        payload = si.generate(FIX / "partial.json")
        record = payload["records"][0]
        self.assertEqual(record["evidence_status"], "partial")
        self.assertIsNone(record["specifications"]["electric_range_km"])
        self.assertIsNone(record["specifications"]["dimensions"])
        self.assertTrue(payload["no_value_inferred"])

    def test_conflicting_evidence_is_reported_not_merged(self):
        payload = si.generate(FIX / "conflicting.json")
        types = {f["finding_type"] for f in payload["findings"]}
        self.assertIn("duplicate_identity", types)
        self.assertIn("conflicting_evidence", types)
        fields = {f.get("field") for f in payload["findings"]}
        self.assertIn("battery_capacity_kwh", fields)
        self.assertEqual(len(payload["records"]), 2)
        self.assertTrue(all(r["evidence_status"] == "conflicting" for r in payload["records"]))

    def test_invalid_fixture_is_rejected(self):
        payload = si.generate(FIX / "invalid.json")
        self.assertEqual(payload["accepted_count"], 0)
        self.assertEqual(payload["rejected_count"], 1)
        self.assertEqual(payload["records"], [])
        self.assertTrue(payload["rejected"][0]["errors"])

    def test_canonical_records_validate_against_schema(self):
        Draft7Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))
        validator = Draft7Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
        for name in ("complete.json", "partial.json", "conflicting.json"):
            for record in si.generate(FIX / name)["records"]:
                self.assertEqual(list(validator.iter_errors(record)), [], name)

    def test_identity_values_are_preserved_exactly(self):
        source = load("complete.json")[0]["identity"]
        canonical = si.generate(FIX / "complete.json")["records"][0]["identity"]
        for field in ("make", "model", "variant", "model_year", "model_specific_id"):
            self.assertEqual(canonical[field], source[field])


class SafetyAndDeterminismTests(unittest.TestCase):
    def test_output_is_byte_stable(self):
        first = json.dumps(si.generate(FIX / "complete.json"), sort_keys=True)
        second = json.dumps(si.generate(FIX / "complete.json"), sort_keys=True)
        self.assertEqual(first, second)

    def test_no_timestamps_in_output(self):
        payload = si.generate(FIX / "complete.json")
        self.assertNotIn("generated_at", payload)
        self.assertNotIn("retrieved_at", payload)

    def test_unsafe_report_paths_are_refused(self):
        for path in (ROOT / "catalog/x.json", ROOT / "catalog/variants/x.json", ROOT / "staging/x.json"):
            with self.subTest(path=path), self.assertRaises(si.SpecError) as ctx:
                si.safe_report_path(path)
            self.assertEqual(ctx.exception.code, "UNSAFE_REPORT_PATH")

    def test_docs_report_path_is_allowed(self):
        self.assertEqual(si.safe_report_path(ROOT / "docs/research/spec.json"),
                         (ROOT / "docs/research/spec.json").resolve())

    def test_check_mode_writes_nothing(self):
        before = {p.name: p.read_bytes() for p in FIX.glob("*.json")}
        self.assertEqual(si.main(["--check", "--input", str(FIX / "complete.json")]), 0)
        after = {p.name: p.read_bytes() for p in FIX.glob("*.json")}
        self.assertEqual(before, after)

    def test_inputs_are_byte_identical_after_generation(self):
        path = FIX / "complete.json"
        before = path.read_bytes()
        si.generate(path)
        self.assertEqual(path.read_bytes(), before)

    def test_no_mutations_are_recorded(self):
        payload = si.generate(FIX / "complete.json")
        for key in ("catalog_writes", "staging_writes", "provider_calls"):
            self.assertEqual(payload[key], 0)


if __name__ == "__main__":
    unittest.main()
