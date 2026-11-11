"""Regression tests for Hive outcome taxonomy, counters and legacy quarantine."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hive_outcomes as outcomes


class OutcomeClassificationTests(unittest.TestCase):
    def test_provider_transport_does_not_consume_quality_budget(self):
        self.assertEqual(outcomes.classify_research_response(None, None), outcomes.PROVIDER_TRANSPORT_FAILURE)
        self.assertEqual(outcomes.classify_audit_results([{"verdict": "PASS"}, {"verdict": "OFFLINE"}]), outcomes.PROVIDER_TRANSPORT_FAILURE)
        entry, retry = outcomes.record_outcome({"variant_id": "a"}, None, outcomes.PROVIDER_TRANSPORT_FAILURE, stage="research", now="2026-11-11T00:00:00Z", attempt_id="a1")
        self.assertTrue(retry)
        self.assertEqual(entry["outcome"]["counters"]["attempts"], 0)
        self.assertEqual(entry["outcome"]["counters"]["provider_attempts"], 1)

    def test_malformed_research_and_audit_responses_use_format_budget(self):
        self.assertEqual(outcomes.classify_research_response("not-json", None), outcomes.RESPONSE_FORMAT_FAILURE)
        self.assertEqual(outcomes.classify_audit_results([{"verdict": "PASS"}, {"verdict": "INVALID_AUDIT_RESPONSE"}]), outcomes.RESPONSE_FORMAT_FAILURE)
        entry, retry = outcomes.record_outcome({"variant_id": "a"}, None, outcomes.RESPONSE_FORMAT_FAILURE, stage="audit")
        self.assertTrue(retry)
        self.assertEqual(entry["outcome"]["counters"]["format_attempts"], 1)
        self.assertEqual(entry["outcome"]["counters"]["attempts"], 0)

    def test_vehicle_quality_rejection_consumes_only_quality_budget(self):
        code = outcomes.classify_audit_results([{"verdict": "FAIL: drivetrain value conflicts with the source"}, {"verdict": "PASS"}])
        self.assertEqual(code, outcomes.VEHICLE_QUALITY_REJECTION)
        entry, retry = outcomes.record_outcome({"variant_id": "a"}, None, code, stage="audit")
        self.assertTrue(retry)
        self.assertEqual(entry["outcome"]["counters"]["attempts"], 1)
        self.assertEqual(entry["outcome"]["counters"]["provider_attempts"], 0)

    def test_provenance_rejection_has_separate_bounded_budget(self):
        code = outcomes.classify_audit_results([{"verdict": "FAIL: provenance URL is not an official source"}, {"verdict": "PASS"}])
        self.assertEqual(code, outcomes.PROVENANCE_REJECTION)
        previous = None
        for expected in (1, 2):
            previous, retry = outcomes.record_outcome({"variant_id": "a"}, previous, code, stage="audit")
            self.assertEqual(previous["outcome"]["counters"]["provenance_attempts"], expected)
            self.assertEqual(previous["outcome"]["counters"]["attempts"], 0)
            self.assertEqual(retry, expected < 2)

    def test_each_failure_counter_is_bounded(self):
        previous = None
        for expected in (1, 2, 3):
            previous, retry = outcomes.record_outcome({"variant_id": "a"}, previous, outcomes.PROVIDER_TRANSPORT_FAILURE, stage="research")
            self.assertEqual(previous["outcome"]["counters"]["provider_attempts"], expected)
            self.assertEqual(retry, expected < 3)

    def test_restart_reload_preserves_class_and_counters(self):
        entry, _ = outcomes.record_outcome({"variant_id": "a"}, None, outcomes.RESPONSE_FORMAT_FAILURE, stage="research", attempt_id="stable-attempt")
        import json
        restored = json.loads(json.dumps(entry))
        next_entry, _ = outcomes.record_outcome({"variant_id": "a"}, restored, outcomes.RESPONSE_FORMAT_FAILURE, stage="research")
        self.assertEqual(next_entry["outcome"]["counters"]["format_attempts"], 2)
        self.assertEqual(next_entry["outcome"]["code"], outcomes.RESPONSE_FORMAT_FAILURE)

    def test_legacy_and_unknown_outcomes_fail_closed_to_manual_review(self):
        legacy = {"task": {"variant_id": "old"}, "verdict": "INDEPENDENT_AUDIT_FAILED", "attempts": 1}
        entry, retry = outcomes.record_outcome(legacy["task"], legacy, outcomes.VEHICLE_QUALITY_REJECTION, stage="audit")
        self.assertEqual(entry["outcome"]["code"], outcomes.MANUAL_REVIEW_REQUIRED)
        self.assertFalse(retry)
        self.assertTrue(outcomes.requires_manual_review(legacy))
        unknown = {"outcome": {"schema_version": 1, "code": "future_unknown", "counters": {}}}
        self.assertTrue(outcomes.requires_manual_review(unknown))

    def test_success_requires_no_failure_record_and_explicitly_clears(self):
        self.assertEqual(outcomes.classify_audit_results([{"verdict": "PASS"}, {"verdict": "PASS"}]), outcomes.AUDIT_SUCCESS)

    def test_safe_metadata_excludes_raw_outputs_and_secrets(self):
        entry, _ = outcomes.record_outcome({"variant_id": "a"}, None, outcomes.PROVIDER_TRANSPORT_FAILURE, stage="research", provider_statuses=[{"provider": "qwen", "status": "OFFLINE", "raw": "secret response", "api_key": "secret"}])
        serialized = str(entry["outcome"])
        self.assertNotIn("secret", serialized)
        self.assertNotIn("raw", serialized)


if __name__ == "__main__":
    unittest.main()