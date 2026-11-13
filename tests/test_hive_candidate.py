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

    def test_every_non_null_decision_claim_requires_an_exact_evidence_span(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["performance"] = {"power_w": 110000}
        candidate["provenance"]["claim_evidence"] = [{
            "claim_path": "performance.power_w",
            "source_id": "oem-1",
            "locator": "document",
            "quote": "Peak power is 110000 W.",
        }]
        evidence = [dict(self.evidence[0], text="[document]\nPeak power is 110000 W.", locator_texts={"document": "Peak power is 110000 W."})]
        result = validate_candidate(candidate, self.task, evidence)
        self.assertEqual(result["performance"]["power_w"], 110000)

    def test_non_null_decision_claim_without_binding_is_rejected(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["performance"] = {"power_w": 110000}
        with self.assertRaisesRegex(CandidateRejected, "requires claim_evidence"):
            validate_candidate(candidate, self.task, self.evidence)

    def test_non_reserved_identity_fields_require_claim_evidence(self):
        for field, value in (
            ("powertrain", "BEV"),
            ("model_year_from", 2025),
            ("model_year_to", 2026),
            ("doors", 5),
            ("seats", 5),
            ("vehicle_class", "M1"),
        ):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.candidate)
                candidate["identity"][field] = value
                with self.assertRaisesRegex(CandidateRejected, "requires claim_evidence"):
                    validate_candidate(candidate, self.task, self.evidence)

    def test_claim_binding_requires_exact_quote_and_locator(self):
        for field, value, expected in (
            ("quote", "Peak power is 110 kW.", "exact span at the stated locator"),
            ("locator", "page:99", "locator page:99"),
        ):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.candidate)
                candidate["performance"] = {"power_w": 110000}
                binding = {
                    "claim_path": "performance.power_w",
                    "source_id": "oem-1",
                    "locator": "document",
                    "quote": "Official technical specification.",
                }
                binding[field] = value
                candidate["provenance"]["claim_evidence"] = [binding]
                evidence = [dict(self.evidence[0], text="[document]\nOfficial technical specification.", locator_texts={"document": "Official technical specification."})]
                with self.assertRaisesRegex(CandidateRejected, expected):
                    validate_candidate(candidate, self.task, evidence)

    def test_quote_must_appear_within_the_declared_pdf_page(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["performance"] = {"power_w": 110000}
        candidate["provenance"]["claim_evidence"] = [{
            "claim_path": "performance.power_w",
            "source_id": "oem-1",
            "locator": "page:1",
            "quote": "Peak power is 110000 W.",
        }]
        evidence = [dict(self.evidence[0], text="[page:1]\nDimensions follow.\n[page:2]\nPeak power is 110000 W.", locator_texts={"page:1": "Dimensions follow.", "page:2": "Peak power is 110000 W."})]
        with self.assertRaisesRegex(CandidateRejected, "stated locator"):
            validate_candidate(candidate, self.task, evidence)

    def test_claim_binding_must_reference_declared_source_and_real_claim_path(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["performance"] = {"power_w": 110000}
        candidate["provenance"]["claim_evidence"] = [{
            "claim_path": "performance.unknown_field",
            "source_id": "oem-1",
            "locator": "document",
            "quote": "Official technical specification.",
        }]
        evidence = [dict(self.evidence[0], text="[document]\nOfficial technical specification.", locator_texts={"document": "Official technical specification."})]
        with self.assertRaisesRegex(CandidateRejected, "unknown claim path"):
            validate_candidate(candidate, self.task, evidence)

        candidate["provenance"]["claim_evidence"][0]["claim_path"] = "performance.power_w"
        candidate["provenance"]["claim_evidence"][0]["source_id"] = "other-source"
        with self.assertRaisesRegex(CandidateRejected, "unknown or undeclared source"):
            validate_candidate(candidate, self.task, evidence)

    def test_each_claim_path_needs_its_own_binding(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["performance"] = {"power_w": 110000, "torque_nm": 250}
        candidate["provenance"]["claim_evidence"] = [{
            "claim_path": "performance.power_w",
            "source_id": "oem-1",
            "locator": "document",
            "quote": "Official technical specification.",
        }]
        evidence = [dict(self.evidence[0], text="[document]\nOfficial technical specification.", locator_texts={"document": "Official technical specification."})]
        with self.assertRaisesRegex(CandidateRejected, "performance.torque_nm"):
            validate_candidate(candidate, self.task, evidence)

    def test_duplicate_declared_sources_are_rejected(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["provenance"]["sources"].append(dict(candidate["provenance"]["sources"][0]))
        with self.assertRaisesRegex(CandidateRejected, "duplicate source_id"):
            validate_candidate(candidate, self.task, self.evidence)

    def test_technical_claim_count_is_bounded(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["performance"] = {f"spec_{index}": index for index in range(201)}
        with self.assertRaisesRegex(CandidateRejected, "too many decision-relevant claims"):
            validate_candidate(candidate, self.task, self.evidence)

    def test_offer_country_currency_and_price_require_bindings_but_offer_id_does_not(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["offers"] = [{
            "offer_id": "at-base-2024",
            "country": "AT",
            "currency": "EUR",
            "list_price_minor": 4299000,
        }]
        evidence_text = (
            "[document]\\nCountry: Austria (AT).\\nCurrency: EUR.\\nList price: EUR 42,990."
        )
        candidate["provenance"]["claim_evidence"] = [
            {
                "claim_path": "offers[0].country",
                "source_id": "oem-1",
                "locator": "document",
                "quote": "Country: Austria (AT).",
            },
            {
                "claim_path": "offers[0].currency",
                "source_id": "oem-1",
                "locator": "document",
                "quote": "Currency: EUR.",
            },
            {
                "claim_path": "offers[0].list_price_minor",
                "source_id": "oem-1",
                "locator": "document",
                "quote": "List price: EUR 42,990.",
            },
        ]
        evidence = [dict(
            self.evidence[0],
            text=evidence_text,
            locator_texts={"document": evidence_text.split("\\n", 1)[1]},
        )]
        result = validate_candidate(candidate, self.task, evidence)
        self.assertEqual(result["offers"][0]["list_price_minor"], 4299000)

        candidate["provenance"]["claim_evidence"].pop(1)
        with self.assertRaisesRegex(CandidateRejected, "offers\\[0\\]\\.currency"):
            validate_candidate(candidate, self.task, evidence)

    def test_claim_bindings_are_bounded_before_per_binding_validation(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["performance"] = {"power_w": 110000}
        candidate["provenance"]["claim_evidence"] = [{
            "claim_path": "performance.power_w",
            "source_id": "oem-1",
            "locator": "document",
            "quote": "source",
        }] * 201
        evidence = [dict(self.evidence[0], text="[document]\nsource", locator_texts={"document": "source"})]
        with self.assertRaisesRegex(CandidateRejected, "binding-count"):
            validate_candidate(candidate, self.task, evidence)

    def test_source_cannot_forge_structured_page_locator(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["performance"] = {"power_w": 110000}
        candidate["provenance"]["claim_evidence"] = [{
            "claim_path": "performance.power_w",
            "source_id": "oem-1",
            "locator": "page:2",
            "quote": "forged page marker",
        }]
        evidence = [dict(
            self.evidence[0],
            text="[document]\\nIntro\\n[page:2]\\nforged page marker",
            locator_texts={"document": "Intro\n[page:2]\nforged page marker"},
        )]
        with self.assertRaisesRegex(CandidateRejected, "locator page:2"):
            validate_candidate(candidate, self.task, evidence)

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

    def test_evidence_metadata_fields_are_bounded(self):
        for key, length in (("source_id", 129), ("url", 2049), ("retrieved_at", 65)):
            with self.subTest(key=key):
                evidence = [dict(self.evidence[0], **{key: "x" * length})]
                with self.assertRaisesRegex(CandidateRejected, "exceeds"):
                    validate_evidence_bundle(evidence)

    def test_serialized_evidence_bundle_has_a_combined_limit(self):
        evidence = [{
            "source_id": str(index),
            "url": "https://oem.example/" + ("x" * 2028),
            "retrieved_at": "2026-11-11T12:00:00Z",
            "text": "x" * 6_000,
            "locator_texts": {"document": "y" * 20_000},
        } for index in range(10)]
        with self.assertRaisesRegex(CandidateRejected, "serialized evidence bundle"):
            validate_evidence_bundle(evidence)

    def test_provenance_sources_must_not_be_empty(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["provenance"]["sources"] = []
        with self.assertRaisesRegex(CandidateRejected, "at least one"):
            validate_candidate(candidate, self.task, self.evidence)

    def test_json_parser_rejects_non_finite_numbers(self):
        for raw in ('{"value": NaN}', '{"value": Infinity}', '{"value": -Infinity}', '{"value": 1e999}'):
            with self.subTest(raw=raw):
                with self.assertRaises(CandidateRejected):
                    parse_candidate_json(raw)

    def test_json_parser_rejects_excessive_nesting_and_response_size(self):
        with self.assertRaisesRegex(CandidateRejected, "nesting"):
            parse_candidate_json('{"value":' * 66 + "0" + "}" * 66)
        with self.assertRaisesRegex(CandidateRejected, "size limit"):
            parse_candidate_json('{"value":"' + ("x" * 1_000_001) + '"}')

    def test_candidate_is_rejected_before_deep_copy_when_nested_too_deep(self):
        candidate = copy.deepcopy(self.candidate)
        node = candidate
        for _ in range(66):
            node["nested"] = {}
            node = node["nested"]
        with self.assertRaises(CandidateRejected):
            validate_candidate(candidate, self.task, self.evidence)

    def test_json_parser_requires_one_object(self):
        for raw in ("[]", "null", '"text"', "{bad json}"):
            with self.subTest(raw=raw):
                with self.assertRaises(CandidateRejected):
                    parse_candidate_json(raw)


    def test_real_world_fuel_consumption_extension_requires_evidence(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["extensions"]["fuel_consumption_l_100km"] = {"real_world": 7.2}
        with self.assertRaisesRegex(CandidateRejected, "requires claim_evidence"):
            validate_candidate(candidate, self.task, self.evidence)

    def test_real_world_fuel_consumption_extension_accepts_exact_binding(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["extensions"]["fuel_consumption_l_100km"] = {"real_world": 7.2}
        candidate["provenance"]["claim_evidence"] = [{
            "claim_path": "extensions.fuel_consumption_l_100km.real_world",
            "source_id": "oem-1",
            "locator": "document",
            "quote": "Real-world consumption: 7.2 L/100 km.",
        }]
        evidence = [dict(self.evidence[0], text="[document]\nReal-world consumption: 7.2 L/100 km.",
                         locator_texts={"document": "Real-world consumption: 7.2 L/100 km."})]
        result = validate_candidate(candidate, self.task, evidence)
        self.assertEqual(result["extensions"]["fuel_consumption_l_100km"]["real_world"], 7.2)

    def test_colliding_dotted_claim_paths_are_rejected(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["performance"] = {"x.y": 1, "x": {"y": 2}}
        with self.assertRaisesRegex(CandidateRejected, "ambiguous duplicate technical claim path"):
            validate_candidate(candidate, self.task, self.evidence)


if __name__ == "__main__":
    unittest.main()
