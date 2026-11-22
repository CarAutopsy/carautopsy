"""Tests for the offline evidence-sprint pipeline."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evidence_sprint as sprint

FIXTURE = ROOT / "tests/fixtures/evidence_sprint/gap_classes.json"


def valid_entry(**overrides):
    entry = {
        "brand": "FixtureBrand", "model": "M1", "tier": "unavailable", "wave": 1,
        "gap_class": "needs_austrian_official_price",
        "required_evidence": "dated AT price", "best_source_type": "AT manufacturer page",
        "next_action": "owner manual check", "next_evidence_batch": True,
        "remain_unavailable": True,
    }
    entry.update(overrides)
    return entry


class AssignmentValidationTests(unittest.TestCase):
    def test_gap_class_fixture_covers_all_six_classes(self):
        entries = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 6)
        self.assertEqual({e["gap_class"] for e in entries}, sprint.GAP_CLASSES)
        for entry in entries:
            self.assertEqual(sprint.validate_assignment(entry), [])

    def test_missing_required_field_is_rejected(self):
        entry = valid_entry()
        entry.pop("next_action")
        self.assertTrue(any("missing required field: next_action" in e
                            for e in sprint.validate_assignment(entry)))

    def test_unknown_gap_class_is_rejected(self):
        self.assertTrue(any("unknown gap class" in e
                            for e in sprint.validate_assignment(valid_entry(gap_class="made_up"))))

    def test_invalid_wave_is_rejected(self):
        self.assertTrue(any("invalid wave" in e
                            for e in sprint.validate_assignment(valid_entry(wave=9))))

    def test_unsupported_price_claim_is_rejected(self):
        self.assertTrue(any("unsupported price claim" in e
                            for e in sprint.validate_assignment(valid_entry(tier="verified"))))

    def test_unsupported_provenance_claim_is_rejected(self):
        self.assertTrue(any("best_source_type" in e
                            for e in sprint.validate_assignment(valid_entry(best_source_type=""))))

    def test_remain_unavailable_false_is_rejected(self):
        self.assertTrue(any("remain_unavailable" in e
                            for e in sprint.validate_assignment(valid_entry(remain_unavailable=False))))

    def test_next_evidence_batch_must_be_boolean(self):
        self.assertTrue(any("next_evidence_batch" in e
                            for e in sprint.validate_assignment(valid_entry(next_evidence_batch="yes"))))


class CandidateClaimTests(unittest.TestCase):
    def test_null_price_fields_are_accepted(self):
        self.assertEqual(sprint.validate_candidate_claim({"price_tier": "unavailable",
                          "price_value": None, "price_low": None, "price_high": None}), [])

    def test_non_null_price_is_rejected(self):
        errors = sprint.validate_candidate_claim({"price_tier": "unavailable", "price_value": 1.0})
        self.assertTrue(any("unsupported price claim" in e for e in errors))

    def test_non_unavailable_candidate_is_rejected(self):
        errors = sprint.validate_candidate_claim({"price_tier": "approximate"})
        self.assertTrue(any("not unavailable" in e for e in errors))


class BatchValidationTests(unittest.TestCase):
    def test_duplicate_model_identity_is_rejected(self):
        entries = [valid_entry(model="M1"), valid_entry(model="m1")]
        candidates = [
            {"brand": "FixtureBrand", "model": "M1", "price_tier": "unavailable"},
            {"brand": "FixtureBrand", "model": "m1", "price_tier": "unavailable"},
        ]
        errors = sprint.validate_batch(entries, candidates)
        self.assertTrue(any("duplicate model identity" in e for e in errors))

    def test_assignment_without_candidate_is_rejected(self):
        errors = sprint.validate_batch([valid_entry()], [])
        self.assertTrue(any("assignment without unavailable candidate" in e for e in errors))

    def test_count_mismatch_is_rejected(self):
        candidate = {"brand": "FixtureBrand", "model": "M1", "price_tier": "unavailable"}
        errors = sprint.validate_batch([valid_entry()], [candidate, dict(candidate, model="M2")])
        self.assertTrue(any("count mismatch" in e for e in errors))


class OutputTests(unittest.TestCase):
    def test_committed_data_generates_36_entries_with_exact_counts(self):
        payload = sprint.generate()
        self.assertEqual(payload["candidate_count"], 36)
        self.assertEqual(payload["wave_counts"], {"1": 9, "2": 18, "3": 9})
        self.assertEqual(payload["gap_class_counts"], {
            "needs_austrian_official_price": 23,
            "needs_dated_australian_dealer_price": 4,
            "needs_cross_market_evidence": 2,
            "needs_owner_decision": 1,
            "needs_specification_completion": 1,
            "not_offered_in_austria": 5,
        })
        self.assertEqual(len(payload["entries"]), 36)
        self.assertEqual(payload["catalog_writes"], 0)
        self.assertEqual(payload["staging_writes"], 0)
        self.assertEqual(payload["provider_calls"], 0)

    def test_every_output_field_is_present(self):
        payload = sprint.generate()
        for entry in payload["entries"]:
            self.assertEqual(list(entry.keys()), list(sprint.REQUIRED_FIELDS))

    def test_output_is_deterministic(self):
        self.assertEqual(sprint.generate(), sprint.generate())

    def test_output_contains_source_hashes_and_no_timestamps(self):
        payload = sprint.generate()
        self.assertEqual(len(payload["candidate_sha256"]), 64)
        self.assertEqual(len(payload["assignment_sha256"]), 64)
        self.assertNotIn("generated_at", payload)


class PathSafetyTests(unittest.TestCase):
    def test_catalog_and_staging_report_paths_are_blocked(self):
        for path in (ROOT / "catalog/variants/x.json", ROOT / "staging/x.json", ROOT / "x.json"):
            with self.subTest(path=path), self.assertRaises(sprint.SprintError) as ctx:
                sprint.safe_report_path(path)
            self.assertEqual(ctx.exception.code, "UNSAFE_REPORT_PATH")

    def test_docs_research_report_path_is_allowed(self):
        self.assertEqual(sprint.safe_report_path(ROOT / "docs/research/out.json"),
                         (ROOT / "docs/research/out.json").resolve())

    def test_check_mode_writes_nothing(self):
        self.assertEqual(sprint.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
