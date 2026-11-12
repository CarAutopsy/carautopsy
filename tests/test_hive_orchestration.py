"""Zero-bypass tests for the runtime orchestration seam.

All transport, extraction, researcher, and auditor interactions are mocked.
No live retrieval, provider call, queue mutation, ledger mutation, or catalog
mutation occurs in these tests.
"""
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from scripts.hive_orchestration import (
    OrchestrationRejected,
    collect_reserved_batch,
    prepare_validated_research_task,
    run_hive_research_and_audit,
)


SCHEMA = {"type": "object"}
URL = "https://oem.example/specs/model.html"
ROBOTS_URL = "https://oem.example/robots.txt"
SOURCE_ID = "d91fac58588248c48d775c95"
CONFIG = {
    "version": 1,
    "approved_hosts": ["oem.example"],
    "source_policies": [{
        "host": "oem.example",
        "automated_access_allowed": True,
        "terms_url": "https://oem.example/terms",
        "terms_reviewed_at": "2026-11-01",
        "terms_reviewed_by": "repository-owner",
        "terms_review_ref": "https://github.com/CarAutopsy/carautopsy/issues/37",
        "approved_urls": [{"url": URL, "variant_ids": ["synthetic.model-x"]}],
    }],
}
TASK = {"variant_id": "synthetic.model-x", "make": "Synthetic", "model": "Model X"}
EVIDENCE = [{
    "source_id": SOURCE_ID,
    "url": URL,
    "retrieved_at": "2026-11-12T00:00:00Z",
    "text": "[document]\nOfficial technical specification.",
    "locator_texts": {"document": "Official technical specification."},
}]
CANDIDATE = {
    "schema_version": "1.0.0",
    "variant_id": "synthetic.model-x",
    "status": "production",
    "identity": {"make": "Synthetic", "model": "Model X"},
    "performance": {"power_w": 110000},
    "provenance": {
        "sources": [{"source_id": SOURCE_ID, "url": URL}],
        "claim_evidence": [{
            "claim_path": "performance.power_w",
            "source_id": SOURCE_ID,
            "locator": "document",
            "quote": "Official technical specification.",
        }],
    },
}


def fetcher(url, **kwargs):
    if url == ROBOTS_URL:
        return SimpleNamespace(outcome="retrieved_unverified", body=b"User-agent: *\nAllow: /\n")
    return SimpleNamespace(
        outcome="retrieved_unverified",
        body=b"official source bytes",
        content_type="text/plain",
        retrieved_at="2026-11-12T00:00:00Z",
    )


def extractor(body, content_type, max_chars):
    return SimpleNamespace(
        text="Official technical specification.",
        locators=("document",),
        locator_texts={"document": "Official technical specification."},
    )


class OrchestrationSeamTests(unittest.TestCase):
    def test_valid_path_returns_candidate_and_exact_evidence(self):
        researcher = Mock(return_value=json.dumps(CANDIDATE))
        result = prepare_validated_research_task(
            reserved_task=TASK,
            schema=SCHEMA,
            config=CONFIG,
            fetcher=fetcher,
            extractor=extractor,
            researcher=researcher,
            today=date(2026, 11, 12),
        )
        self.assertEqual(result.candidate["performance"]["power_w"], 110000)
        self.assertEqual(result.evidence, EVIDENCE)
        self.assertEqual(result.source_ids, (SOURCE_ID,))
        researcher.assert_called_once()

    def test_empty_manifest_stops_before_researcher(self):
        researcher = Mock()
        with self.assertRaises(OrchestrationRejected):
            prepare_validated_research_task(
                reserved_task=TASK,
                schema=SCHEMA,
                config={"version": 1, "approved_hosts": [], "source_policies": []},
                fetcher=Mock(),
                extractor=Mock(),
                researcher=researcher,
                today=date(2026, 11, 12),
            )
        researcher.assert_not_called()

    def test_policy_or_transport_failure_stops_before_researcher(self):
        researcher = Mock()
        with self.assertRaises(OrchestrationRejected):
            prepare_validated_research_task(
                reserved_task=TASK,
                schema=SCHEMA,
                config=CONFIG,
                fetcher=Mock(side_effect=RuntimeError("network")),
                extractor=extractor,
                researcher=researcher,
                today=date(2026, 11, 12),
            )
        researcher.assert_not_called()

    def test_extraction_failure_stops_before_researcher(self):
        researcher = Mock()
        with self.assertRaises(OrchestrationRejected):
            prepare_validated_research_task(
                reserved_task=TASK,
                schema=SCHEMA,
                config=CONFIG,
                fetcher=fetcher,
                extractor=Mock(side_effect=ValueError("bad document")),
                researcher=researcher,
                today=date(2026, 11, 12),
            )
        researcher.assert_not_called()

    def test_malformed_researcher_response_stops_before_auditor(self):
        researcher = Mock(return_value="not-json")
        with self.assertRaises(OrchestrationRejected):
            prepare_validated_research_task(
                reserved_task=TASK,
                schema=SCHEMA,
                config=CONFIG,
                fetcher=fetcher,
                extractor=extractor,
                researcher=researcher,
                today=date(2026, 11, 12),
            )

    def test_reserved_identity_cannot_be_repaired_by_model(self):
        researcher = Mock(return_value=json.dumps({**CANDIDATE, "identity": {"make": "Other", "model": "Other"}}))
        with self.assertRaises(OrchestrationRejected):
            prepare_validated_research_task(
                reserved_task=TASK,
                schema=SCHEMA,
                config=CONFIG,
                fetcher=fetcher,
                extractor=extractor,
                researcher=researcher,
                today=date(2026, 11, 12),
            )

    def test_missing_claim_binding_stops_before_auditor(self):
        candidate = json.loads(json.dumps(CANDIDATE))
        candidate["provenance"]["claim_evidence"] = []
        researcher = Mock(return_value=json.dumps(candidate))
        with self.assertRaises(OrchestrationRejected):
            prepare_validated_research_task(
                reserved_task=TASK,
                schema=SCHEMA,
                config=CONFIG,
                fetcher=fetcher,
                extractor=extractor,
                researcher=researcher,
                today=date(2026, 11, 12),
            )

    def test_result_contains_no_raw_bytes_or_secrets(self):
        researcher = Mock(return_value=json.dumps(CANDIDATE))
        result = prepare_validated_research_task(
            reserved_task=TASK,
            schema=SCHEMA,
            config=CONFIG,
            fetcher=fetcher,
            extractor=extractor,
            researcher=researcher,
            today=date(2026, 11, 12),
        )
        serialized = json.dumps(result.__dict__, default=lambda value: getattr(value, "__dict__", str(value)))
        self.assertNotIn("official source bytes", serialized)
        self.assertNotIn("QWEN_API_KEY", serialized)
        self.assertNotIn("DEEPSEEK_API_KEY", serialized)
        self.assertNotIn("GEMINI_API_KEY", serialized)


    def test_invalid_candidate_never_reaches_paid_auditors(self):
        candidate = json.loads(json.dumps(CANDIDATE))
        candidate["provenance"]["claim_evidence"] = []
        researcher = Mock(return_value=json.dumps(candidate))
        auditor = Mock(return_value=("PASS", "deepseek", None))
        with self.assertRaises(OrchestrationRejected):
            run_hive_research_and_audit(
                reserved_task=TASK,
                schema=SCHEMA,
                config=CONFIG,
                fetcher=fetcher,
                extractor=extractor,
                researcher=researcher,
                auditor=auditor,
                researcher_vendor="qwen",
                today=date(2026, 11, 12),
            )
        auditor.assert_not_called()

    def test_valid_candidate_reaches_two_independent_auditors_with_identical_prompt(self):
        researcher = Mock(return_value=(json.dumps(CANDIDATE), "qwen-intl", "qwen", None))
        auditor = Mock(side_effect=[
            ("PASS", "deepseek", None),
            ("PASS", "gemini", None),
        ])
        result, audits = run_hive_research_and_audit(
            reserved_task=TASK,
            schema=SCHEMA,
            config=CONFIG,
            fetcher=fetcher,
            extractor=extractor,
            researcher=researcher,
            auditor=auditor,
            today=date(2026, 11, 12),
        )
        self.assertEqual([item["vendor"] for item in audits], ["deepseek", "google"])
        self.assertEqual([item["verdict"] for item in audits], ["PASS", "PASS"])
        self.assertEqual(auditor.call_count, 2)
        first_prompt = auditor.call_args_list[0].args[0]
        second_prompt = auditor.call_args_list[1].args[0]
        self.assertEqual(first_prompt, second_prompt)
        self.assertIn("claim_evidence", first_prompt)
        self.assertEqual(result.candidate["variant_id"], TASK["variant_id"])

    def test_invalid_researcher_json_never_reaches_auditors(self):
        researcher = Mock(return_value='{"variant_id": NaN}')
        auditor = Mock(return_value=("PASS", "deepseek", None))
        with self.assertRaises(OrchestrationRejected) as raised:
            run_hive_research_and_audit(
                reserved_task=TASK,
                schema=SCHEMA,
                config=CONFIG,
                fetcher=fetcher,
                extractor=extractor,
                researcher=researcher,
                auditor=auditor,
                researcher_vendor="qwen",
                today=date(2026, 11, 12),
            )
        self.assertEqual(raised.exception.code, "response_format_failure")
        auditor.assert_not_called()


    def test_preflight_evidence_bundle_is_reused_without_second_fetch(self):
        researcher = Mock(return_value=(json.dumps(CANDIDATE), "qwen-intl", "qwen", None))
        fetch = Mock()
        auditor = Mock(side_effect=[
            ("PASS", "deepseek", None),
            ("PASS", "gemini", None),
        ])
        result, audits = run_hive_research_and_audit(
            reserved_task=TASK,
            schema=SCHEMA,
            researcher=researcher,
            auditor=auditor,
            evidence_bundle=EVIDENCE,
            fetcher=fetch,
        )
        fetch.assert_not_called()
        self.assertEqual(result.evidence, EVIDENCE)
        self.assertEqual([item["verdict"] for item in audits], ["PASS", "PASS"])

    def test_invalid_preflight_evidence_stops_before_any_provider(self):
        researcher = Mock()
        auditor = Mock()
        with self.assertRaises(OrchestrationRejected):
            run_hive_research_and_audit(
                reserved_task=TASK,
                schema=SCHEMA,
                researcher=researcher,
                auditor=auditor,
                researcher_vendor="qwen",
                evidence_bundle=[{"source_id": "incomplete"}],
            )
        researcher.assert_not_called()
        auditor.assert_not_called()


    def test_reserved_batch_union_is_deduplicated_across_queue_snapshots(self):
        first = [{"variant_id": "v1", "make": "A", "model": "One"},
                 {"variant_id": "v2", "make": "B", "model": "Two"}]
        second = [{"variant_id": "v1", "make": "A", "model": "One"},
                  {"variant_id": "v3", "make": "C", "model": "Three"}]
        result = collect_reserved_batch([first, second], 2)
        self.assertEqual([item["variant_id"] for item in result], ["v1", "v2", "v3"])

    def test_reserved_batch_rejects_identity_conflict_for_same_variant_id(self):
        first = [{"variant_id": "v1", "make": "A", "model": "One"}]
        second = [{"variant_id": "v1", "make": "A", "model": "Different"}]
        with self.assertRaisesRegex(ValueError, "disagree on reserved identity"):
            collect_reserved_batch([first, second], 2)

    def test_auditor_vendor_selection_deduplicates_independent_vendors(self):
        result = prepare_validated_research_task(
            reserved_task=TASK,
            schema=SCHEMA,
            config=CONFIG,
            fetcher=fetcher,
            extractor=extractor,
            researcher=Mock(return_value=(json.dumps(CANDIDATE), "qwen-intl", "qwen", None)),
            today=date(2026, 11, 12),
        )
        auditor = Mock(return_value=("PASS", "deepseek", None))
        with self.assertRaisesRegex(OrchestrationRejected, "two independent auditor vendors"):
            audit_validated_research_task(
                result,
                schema=SCHEMA,
                researcher_vendor="qwen",
                auditor=auditor,
                auditor_vendors=("qwen", "deepseek", "deepseek"),
            )
        auditor.assert_not_called()

    def test_reserved_batch_skips_catalog_valid_variants_before_batch_limit(self):
        first = [
            {"variant_id": "already.valid", "make": "A", "model": "One"},
            {"variant_id": "needs.research", "make": "B", "model": "Two"},
            {"variant_id": "later.task", "make": "C", "model": "Three"},
        ]
        result = collect_reserved_batch([first], 1, skip_variant_ids={"already.valid"})
        self.assertEqual([item["variant_id"] for item in result], ["needs.research"])

    def test_reserved_batch_rejects_malformed_task_identity(self):
        with self.assertRaisesRegex(ValueError, "missing its reserved variant identity"):
            collect_reserved_batch([[{"variant_id": "v1", "make": "A"}]], 1)


if __name__ == "__main__":
    unittest.main()
