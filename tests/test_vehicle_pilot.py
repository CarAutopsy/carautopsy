"""Fixture-only Austrian vehicle-data pilot demonstration.

Everything here is synthetic and offline. No live URL is fetched, no provider
is called, no source manifest is changed and no result is a verified vehicle
claim. The tests demonstrate the traceability and fail-closed gates that a
future owner-authorized pilot would have to pass.
"""
import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from jsonschema import Draft7Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "pilot"
SCHEMA_PATH = ROOT / "schemas" / "vehicle-variant.schema.json"
sys.path.insert(0, str(ROOT / "scripts"))

from hive_audit import concise_audit_verdict
from hive_candidate import CandidateRejected, validate_candidate
from hive_source_policy import SourcePolicyDenied, check_source_access


URL = "https://oem.example/specs/model-x"
TASK = {"variant_id": "synthetic.at.bev.model-x", "make": "Synthetic", "model": "Model X"}
ROBOTS_ALLOW = b"User-agent: *\nAllow: /\n"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def dual_auditor_accept(vendor_a, verdict_a, vendor_b, verdict_b):
    """Accept only two exact PASS tokens from two different vendors."""
    return (
        vendor_a != vendor_b
        and concise_audit_verdict(verdict_a) == "PASS"
        and concise_audit_verdict(verdict_b) == "PASS"
    )


class VehiclePilotFixtureTests(unittest.TestCase):
    def setUp(self):
        self.record = load("at_bev_synthetic.json")
        self.evidence = [load("at_bev_evidence.json")]
        self.policy = load("at_bev_source_policy.json")

    def test_minimum_record_validates_against_repository_schema(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        self.assertEqual(list(validator.iter_errors(self.record)), [])

    def test_source_to_claim_provenance_passes_deterministic_gate(self):
        original = copy.deepcopy(self.record)
        result = validate_candidate(self.record, TASK, self.evidence)
        self.assertEqual(self.record, original)
        self.assertEqual(result["provenance"]["confidence"], "low")
        self.assertIsNone(result["provenance"]["reviewed_by"])
        self.assertEqual(len(result["provenance"]["claim_evidence"]), 9)

    def test_conflicting_specification_quote_is_rejected(self):
        record = copy.deepcopy(self.record)
        record["provenance"]["claim_evidence"][3]["quote"] = "Continuous power: 999000 W."
        with self.assertRaisesRegex(CandidateRejected, "exact span"):
            validate_candidate(record, TASK, self.evidence)

    def test_missing_schema_field_and_missing_claim_binding_are_rejected(self):
        missing_field = copy.deepcopy(self.record)
        del missing_field["status"]
        with self.assertRaisesRegex(CandidateRejected, "schema violation"):
            validate_candidate(missing_field, TASK, self.evidence)

        missing_binding = copy.deepcopy(self.record)
        missing_binding["provenance"]["claim_evidence"].pop()
        with self.assertRaisesRegex(CandidateRejected, "lack evidence bindings"):
            validate_candidate(missing_binding, TASK, self.evidence)

    def test_expired_source_terms_are_denied_before_any_target_fetch(self):
        fetcher = Mock()
        with self.assertRaisesRegex(SourcePolicyDenied, "stale"):
            check_source_access(
                URL, config=self.policy, fetcher=fetcher, today=date(2027, 6, 1)
            )
        fetcher.assert_not_called()

    def test_unapproved_host_is_denied_before_any_fetch(self):
        fetcher = Mock()
        with self.assertRaises(SourcePolicyDenied):
            check_source_access(
                "https://attacker.example/specs", config=self.policy, fetcher=fetcher,
                today=date(2026, 11, 11),
            )
        fetcher.assert_not_called()

    def test_approved_host_and_url_allow_with_robots_permission(self):
        fetcher = Mock(return_value=SimpleNamespace(outcome="retrieved_unverified", body=ROBOTS_ALLOW))
        self.assertTrue(
            check_source_access(URL, config=self.policy, fetcher=fetcher, today=date(2026, 11, 11))
        )
        self.assertEqual(fetcher.call_args.args[0], "https://oem.example/robots.txt")

    def test_dual_auditor_acceptance_requires_two_independent_exact_passes(self):
        self.assertTrue(dual_auditor_accept("vendor-a", "PASS", "vendor-b", "PASS"))
        self.assertFalse(dual_auditor_accept("vendor-a", "PASS", "vendor-a", "PASS"))
        self.assertFalse(dual_auditor_accept("vendor-a", "PASS", "vendor-b", "PASS with reservations"))
        self.assertFalse(dual_auditor_accept("vendor-a", "PASS", "vendor-b", "PASS\nFAIL: provenance"))
        self.assertFalse(dual_auditor_accept("vendor-a", "PASS", "vendor-b", None))


if __name__ == "__main__":
    unittest.main()
