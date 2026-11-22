"""Tests for offline identity normalization and conflict detection."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import identity_conflicts as ic

FIX = ROOT / "tests/fixtures/identity_conflicts"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class ConflictClassTests(unittest.TestCase):
    def test_all_six_conflict_classes_are_defined(self):
        self.assertEqual(len(ic.CLASSES), 6)

    def test_exact_duplicate(self):
        findings = ic.detect(load("exact_duplicate.json"))
        self.assertTrue(any(f["recommended_resolution"] == "exact_duplicate" for f in findings))

    def test_near_duplicate_is_probable_duplicate_owner_review(self):
        findings = ic.detect(load("near_duplicate.json"))
        self.assertTrue(any(f["recommended_resolution"] == "probable_duplicate_owner_review"
                            for f in findings))

    def test_conflicting_model_year(self):
        findings = ic.detect(load("conflicting_model_year.json"))
        self.assertTrue(any(f["conflicting_field"] == "model_year"
                            and f["recommended_resolution"] == "conflicting_attribute"
                            for f in findings))

    def test_conflicting_powertrain(self):
        findings = ic.detect(load("conflicting_powertrain.json"))
        self.assertTrue(any(f["conflicting_field"] == "powertrain"
                            for f in findings))

    def test_conflicting_battery_and_range(self):
        findings = ic.detect(load("conflicting_battery_range.json"))
        fields = {f["conflicting_field"] for f in findings}
        self.assertIn("battery_capacity", fields)
        self.assertIn("range", fields)

    def test_missing_mandatory_identity_field(self):
        findings = ic.detect(load("missing_identity.json"))
        self.assertTrue(any(f["recommended_resolution"] == "missing_mandatory_identity_field"
                            for f in findings))

    def test_ambiguous_variant(self):
        findings = ic.detect(load("ambiguous_variant.json"))
        self.assertEqual(sum(1 for f in findings
                             if f["recommended_resolution"] == "unresolved_variant"), 2)

    def test_unsupported_identity_assertion(self):
        findings = ic.detect(load("unsupported_assertion.json"))
        self.assertTrue(any(f["recommended_resolution"] == "unsupported_identity_assertion"
                            for f in findings))

    def test_synthetic_kodiaq_karoq_style_unresolved_variant(self):
        findings = ic.detect(load("kodiaq_karoq_unresolved.json"))
        unresolved = [f for f in findings if f["recommended_resolution"] == "unresolved_variant"]
        self.assertEqual(len(unresolved), 2)
        for finding in unresolved:
            self.assertIs(finding["owner_decision_required"], True)

    def test_existing_catalog_duplicate_is_reported_and_never_written(self):
        candidates = load("exact_duplicate.json")
        catalog = load("catalog_snapshot.json")
        payload = ic.generate(FIX / "exact_duplicate.json", FIX / "catalog_snapshot.json")
        findings = payload["findings"]
        self.assertTrue(any(f["conflicting_field"] == "existing_catalog_record"
                            and f["recommended_resolution"] == "exact_duplicate"
                            for f in findings))
        self.assertEqual(payload["catalog_writes"], 0)
        self.assertEqual(payload["records_overwritten"], 0)
        self.assertEqual(payload["records_deleted"], 0)
        self.assertEqual(payload["records_promoted"], 0)
        self.assertEqual(payload["records_merged"], 0)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len(catalog), 1)


class ReportSchemaTests(unittest.TestCase):
    def test_findings_have_required_fields(self):
        findings = ic.detect(load("conflicting_model_year.json"))
        for finding in findings:
            for field in ("candidate_identity", "conflicting_field", "competing_values",
                          "source_provenance", "recommended_resolution",
                          "owner_decision_required"):
                self.assertIn(field, finding)
            self.assertIsInstance(finding["owner_decision_required"], bool)
            self.assertIsInstance(finding["competing_values"], list)
            self.assertIsInstance(finding["source_provenance"], list)

    def test_raw_values_are_preserved_in_finding(self):
        records = load("near_duplicate.json")
        findings = ic.detect(records)
        self.assertEqual(findings[0]["candidate_identity"]["make"], "FixtureBrand")
        raw_pairs = findings[0]["competing_values"]
        self.assertIn((" fixturebrand ", " fixturemodel "), raw_pairs)

    def test_input_files_are_reported_read_only(self):
        payload = ic.generate(FIX / "exact_duplicate.json")
        self.assertEqual(len(payload["input_files"]), 1)
        self.assertTrue(payload["input_files"][0]["read_only"])
        self.assertEqual(len(payload["input_files"][0]["sha256"]), 64)


class SafetyTests(unittest.TestCase):
    def test_unsafe_report_paths_are_refused(self):
        for path in (ROOT / "catalog/x.json", ROOT / "catalog/variants/x.json", ROOT / "staging/x.json"):
            with self.subTest(path=path), self.assertRaises(ic.ConflictError) as ctx:
                ic.safe_report_path(path)
            self.assertEqual(ctx.exception.code, "UNSAFE_REPORT_PATH")

    def test_staging_and_catalog_inputs_are_refused(self):
        for path in (ROOT / "staging/pilot-batch-001-002", ROOT / "catalog/variants"):
            with self.subTest(path=path), self.assertRaises(ic.ConflictError) as ctx:
                ic.guard_input_path(path)
            self.assertEqual(ctx.exception.code, "BLOCKED_INPUT_PATH")

    def test_docs_report_path_is_allowed(self):
        self.assertEqual(ic.safe_report_path(ROOT / "docs/research/report.json"),
                         (ROOT / "docs/research/report.json").resolve())

    def test_check_mode_writes_nothing(self):
        before = {p.name: p.read_bytes() for p in FIX.glob("*.json")}
        self.assertEqual(ic.main(["--check", "--candidates", str(FIX / "exact_duplicate.json")]), 0)
        after = {p.name: p.read_bytes() for p in FIX.glob("*.json")}
        self.assertEqual(before, after)

    def test_inputs_are_byte_identical_after_generation(self):
        path = FIX / "exact_duplicate.json"
        before = path.read_bytes()
        ic.generate(path)
        self.assertEqual(path.read_bytes(), before)


class DeterminismTests(unittest.TestCase):
    def test_two_runs_produce_identical_payload(self):
        self.assertEqual(ic.generate(FIX / "exact_duplicate.json"),
                         ic.generate(FIX / "exact_duplicate.json"))

    def test_serialized_output_is_stable(self):
        first = json.dumps(ic.generate(FIX / "conflicting_powertrain.json"), sort_keys=True)
        second = json.dumps(ic.generate(FIX / "conflicting_powertrain.json"), sort_keys=True)
        self.assertEqual(first, second)

    def test_no_timestamps_in_output(self):
        payload = ic.generate(FIX / "exact_duplicate.json")
        self.assertNotIn("generated_at", payload)
        self.assertNotIn("retrieved_at", payload)


if __name__ == "__main__":
    unittest.main()
