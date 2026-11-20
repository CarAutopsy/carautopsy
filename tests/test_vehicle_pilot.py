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
from hive_candidate import CandidateRejected, validate_candidate, validate_evidence_bundle
from hive_source_policy import SourcePolicyDenied, check_source_access
from issue_roadmap import classify_issue
from validate_tco_readiness import validate_variant_readiness


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


class VehiclePilotExpansionTests(unittest.TestCase):
    """Negative and multi-variant pilot cases (issue #129 Phase 5)."""

    def _variant(self, index):
        record = copy.deepcopy(load("at_bev_synthetic.json"))
        source_id = f"oem-synthetic-{index}"
        record["variant_id"] = f"{record['variant_id']}-{index}"
        record["provenance"]["sources"][0]["source_id"] = source_id
        for binding in record["provenance"]["claim_evidence"]:
            binding["source_id"] = source_id
        evidence = copy.deepcopy(load("at_bev_evidence.json"))
        evidence["source_id"] = source_id
        task = {"variant_id": record["variant_id"], "make": "Synthetic", "model": "Model X"}
        return record, evidence, task

    def test_multiple_variants_validate_independently(self):
        first, first_evidence, first_task = self._variant(1)
        second, second_evidence, second_task = self._variant(2)
        evidence = [first_evidence, second_evidence]
        self.assertEqual(validate_candidate(first, first_task, evidence)["variant_id"], first_task["variant_id"])
        self.assertEqual(validate_candidate(second, second_task, evidence)["variant_id"], second_task["variant_id"])

    def test_cross_variant_evidence_contamination_is_rejected(self):
        first, _, first_task = self._variant(1)
        _, second_evidence, _ = self._variant(2)
        with self.assertRaisesRegex(CandidateRejected, "not in the evidence bundle"):
            validate_candidate(first, first_task, [second_evidence])

    def test_missing_motor_power_is_rejected(self):
        record = load("at_bev_synthetic.json")
        del record["performance"]["electric_motor_continuous_power_w"]
        with self.assertRaises(CandidateRejected):
            validate_candidate(record, TASK, [load("at_bev_evidence.json")])

    def test_missing_vehicle_mass_is_rejected(self):
        record = load("at_bev_synthetic.json")
        del record["dimensions"]["max_permissible_mass_kg"]
        with self.assertRaises(CandidateRejected):
            validate_candidate(record, TASK, [load("at_bev_evidence.json")])

    def test_invalid_model_year_boundary_is_rejected_by_readiness_gate(self):
        from validate_tco_readiness import validate_variant_readiness

        record = load("at_bev_synthetic.json")
        record["identity"]["model_year_to"] = 2025
        findings = validate_variant_readiness(record)
        self.assertTrue(
            any("model_year_from must not exceed" in finding for finding in findings)
        )
        record["identity"]["model_year_to"] = 2026
        self.assertFalse(
            any("model_year_from must not exceed" in finding
                for finding in validate_variant_readiness(record))
        )

    def test_duplicate_evidence_is_rejected(self):
        evidence = load("at_bev_evidence.json")
        with self.assertRaisesRegex(CandidateRejected, "duplicate"):
            validate_evidence_bundle([evidence, copy.deepcopy(evidence)])

    def test_incorrect_claim_to_source_binding_is_rejected(self):
        record = load("at_bev_synthetic.json")
        record["provenance"]["claim_evidence"][0]["source_id"] = "unapproved-source"
        with self.assertRaisesRegex(CandidateRejected, "unknown or undeclared source"):
            validate_candidate(record, TASK, [load("at_bev_evidence.json")])

    def test_malformed_auditor_responses_are_invalid(self):
        for raw in ("PASS.", "APPROVED", "PASS\nFAIL: bad", None, ""):
            with self.subTest(raw=raw):
                self.assertEqual(concise_audit_verdict(raw), "INVALID_AUDIT_RESPONSE")

    def test_insufficient_auditor_quorum_is_rejected(self):
        self.assertFalse(dual_auditor_accept("vendor-a", "PASS", "vendor-a", "PASS"))
        self.assertFalse(dual_auditor_accept("vendor-a", "PASS", "vendor-b", "FAIL: bad"))
        self.assertTrue(dual_auditor_accept("vendor-a", "PASS", "vendor-b", "PASS"))

    def test_owner_approval_is_explicit_for_actionable_proposals(self):
        issue = {
            "number": 86, "title": "Synthetic", "state": "open",
            "labels": [{"name": "roadmap:candidate"}],
            "html_url": "https://github.com/CarAutopsy/carautopsy/issues/86",
        }
        proposal = classify_issue(issue)["proposal"]
        self.assertTrue(proposal["requires_owner_approval"])
        self.assertTrue(proposal["owner_input_required"])
        self.assertEqual(proposal["status"], "proposed")


class VehiclePilotTaxInputTests(unittest.TestCase):
    """Readiness-gate edge cases for both BEV and combustion variants."""

    @staticmethod
    def _bev():
        return {
            "identity": {
                "make": "Synthetic", "model": "B", "powertrain": "bev",
                "vehicle_class": "M1", "model_year_from": 2026, "model_year_to": 2026,
            },
            "registration": {"first_registration_date": "2026-01-15"},
            "dimensions": {"max_permissible_mass_kg": 2300, "own_weight_kg": 1850},
            "performance": {"electric_motor_continuous_power_w": 150000},
            "energy": {"consumption_wh_km": {"real_world": 180}},
            "offers": [{"country": "AT", "currency": "EUR", "list_price_minor": 4299000}],
        }

    @staticmethod
    def _ice():
        return {
            "identity": {
                "make": "Synthetic", "model": "C", "powertrain": "ice_petrol",
                "vehicle_class": "M1", "model_year_from": 2026, "model_year_to": 2026,
            },
            "registration": {"first_registration_date": "2026-01-15"},
            "dimensions": {"max_permissible_mass_kg": 2100},
            "performance": {"combustion_engine_power_w": 110000},
            "emissions": {"co2_wltp_gpkm": 132},
            "extensions": {"fuel_consumption_l_100km": {"real_world": 5.6}},
            "offers": [{
                "country": "AT", "currency": "EUR", "list_price_minor": 3299000,
                "purchase_price_excl_vat_eur": 27000.0,
            }],
        }

    def test_complete_bev_and_ice_variants_pass_readiness(self):
        self.assertEqual(validate_variant_readiness(self._bev()), [])
        self.assertEqual(validate_variant_readiness(self._ice()), [])

    def test_missing_continuous_motor_power_is_reported(self):
        record = self._bev()
        del record["performance"]["electric_motor_continuous_power_w"]
        self.assertIn(
            "performance.electric_motor_continuous_power_w",
            validate_variant_readiness(record),
        )

    def test_invalid_mass_values_are_reported(self):
        for mass in (-1, 4000, "heavy", True):
            with self.subTest(mass=mass):
                record = self._bev()
                record["dimensions"]["max_permissible_mass_kg"] = mass
                findings = validate_variant_readiness(record)
                self.assertTrue(any("max_permissible_mass_kg" in item for item in findings))

    def test_incomplete_tax_inputs_are_reported(self):
        bev = self._bev()
        del bev["energy"]
        self.assertTrue(any("consumption_wh_km" in item for item in validate_variant_readiness(bev)))
        ice = self._ice()
        del ice["offers"][0]["purchase_price_excl_vat_eur"]
        self.assertTrue(any("purchase_price_excl_vat_eur" in item for item in validate_variant_readiness(ice)))

    def test_conflicting_duplicate_evidence_is_rejected(self):
        evidence = load("at_bev_evidence.json")
        conflicting = dict(evidence, text=evidence["text"] + "Contradictory specification.")
        with self.assertRaisesRegex(CandidateRejected, "duplicate"):
            validate_evidence_bundle([evidence, conflicting])


if __name__ == "__main__":
    unittest.main()
