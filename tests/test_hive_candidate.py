import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hive_candidate import (
    MAX_EXCERPT_CHARS,
    MAX_TOTAL_EXCERPT_CHARS,
    CandidateRejected,
    parse_candidate_json,
    validate_candidate,
    validate_evidence_bundle,
)


class HiveCandidateGateTests(unittest.TestCase):
    """Exercise schema, reserved identity, evidence, and safe-normalization gates."""

    def setUp(self):
        self.task = {"variant_id": "synthetic.model-x", "make": "Synthetic", "model": "Model X"}
        self.evidence = [{
            "source_id": "oem-1",
            "url": "https://oem.example/specs/model-x",
            "retrieved_at": "2026-11-11T12:00:00Z",
            "text": "Synthetic Model X official technical specification.",
        }]
        self.candidate = {
            "schema_version": "1.0.0",
            "variant_id": "synthetic.model-x",
            "status": "draft",
            "identity": {"make": "Synthetic", "model": "Model X"},
            "provenance": {
                "confidence": "model-invented",
                "reviewed_by": "model-supplied",
                "sources": [{"source_id": "oem-1", "url": self.evidence[0]["url"]}],
            },
            "extensions": {"hive": {"forged": True}, "other": "keep"},
        }

    def test_valid_candidate_is_copied_and_pipeline_metadata_is_normalized(self):
        original = copy.deepcopy(self.candidate)
        result = validate_candidate(self.candidate, self.task, self.evidence)
        self.assertEqual(self.candidate, original)
        self.assertIsNot(result, self.candidate)
        self.assertEqual(result["provenance"]["confidence"], "low")
        self.assertIsNone(result["provenance"]["reviewed_by"])
        self.assertNotIn("hive", result["extensions"])
        self.assertEqual(result["extensions"]["other"], "keep")

    def test_non_object_candidate_is_rejected(self):
        with self.assertRaisesRegex(CandidateRejected, "JSON object"):
            validate_candidate([], self.task, self.evidence)

    def test_reserved_variant_id_make_and_model_are_not_repaired(self):
        for path, value in (
            (("variant_id",), "other.id"),
            (("identity", "make"), "Other"),
            (("identity", "model"), "Other Model"),
        ):
            with self.subTest(path=path):
                candidate = copy.deepcopy(self.candidate)
                target = candidate
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(CandidateRejected):
                    validate_candidate(candidate, self.task, self.evidence)

    def test_malformed_schema_record_is_rejected(self):
        candidate = copy.deepcopy(self.candidate)
        del candidate["status"]
        with self.assertRaisesRegex(CandidateRejected, "schema violation"):
            validate_candidate(candidate, self.task, self.evidence)

    def test_empty_evidence_is_rejected(self):
        with self.assertRaisesRegex(CandidateRejected, "non-empty"):
            validate_candidate(self.candidate, self.task, [])

    def test_evidence_required_fields_are_enforced(self):
        for key in ("source_id", "url", "retrieved_at", "text"):
            with self.subTest(key=key):
                evidence = copy.deepcopy(self.evidence)
                del evidence[0][key]
                with self.assertRaises(CandidateRejected):
                    validate_evidence_bundle(evidence)

    def test_duplicate_source_ids_are_rejected(self):
        evidence = self.evidence + [dict(self.evidence[0])]
        with self.assertRaisesRegex(CandidateRejected, "duplicate"):
            validate_evidence_bundle(evidence)

    def test_excerpt_and_total_size_limits_are_enforced(self):
        too_large = [dict(self.evidence[0], text="x" * (MAX_EXCERPT_CHARS + 1))]
        with self.assertRaisesRegex(CandidateRejected, "excerpt exceeds"):
            validate_evidence_bundle(too_large)
        total_over = [
            {"source_id": str(i), "url": f"https://oem.example/{i}",
             "retrieved_at": "2026-11-11", "text": "x" * 15_001}
            for i in range(4)
        ]
        with self.assertRaisesRegex(CandidateRejected, "combined evidence"):
            validate_evidence_bundle(total_over)

    def test_exact_excerpt_and_combined_size_boundaries_are_allowed(self):
        evidence = [
            {"source_id": str(i), "url": f"https://oem.example/{i}",
             "retrieved_at": "2026-11-11", "text": "x" * 15_000}
            for i in range(4)
        ]
        self.assertEqual(sum(len(item["text"]) for item in validate_evidence_bundle(evidence)),
                         MAX_TOTAL_EXCERPT_CHARS)
        self.assertEqual(MAX_EXCERPT_CHARS, 20_000)

    def test_too_many_evidence_sources_are_rejected(self):
        evidence = [
            {"source_id": str(i), "url": f"https://oem.example/{i}",
             "retrieved_at": "2026-11-11", "text": "source"}
            for i in range(11)
        ]
        with self.assertRaisesRegex(CandidateRejected, "source-count"):
            validate_evidence_bundle(evidence)

    def test_provenance_must_reference_supplied_evidence(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["provenance"]["sources"][0]["source_id"] = "not-supplied"
        with self.assertRaisesRegex(CandidateRejected, "not in the evidence"):
            validate_candidate(candidate, self.task, self.evidence)

    def test_provenance_url_must_match_source_id(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["provenance"]["sources"][0]["url"] = "https://other.example/"
        with self.assertRaisesRegex(CandidateRejected, "does not match"):
            validate_candidate(candidate, self.task, self.evidence)

    def test_provenance_sources_must_not_be_empty(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["provenance"]["sources"] = []
        with self.assertRaisesRegex(CandidateRejected, "at least one"):
            validate_candidate(candidate, self.task, self.evidence)

    def test_json_parser_rejects_non_finite_numbers(self):
        for raw in ('{"value": NaN}', '{"value": Infinity}', '{"value": -Infinity}'):
            with self.subTest(raw=raw):
                with self.assertRaises(CandidateRejected):
                    parse_candidate_json(raw)

    def test_json_parser_requires_one_object(self):
        for raw in ("[]", "null", '"text"', "{bad json}"):
            with self.subTest(raw=raw):
                with self.assertRaises(CandidateRejected):
                    parse_candidate_json(raw)


if __name__ == "__main__":
    unittest.main()
