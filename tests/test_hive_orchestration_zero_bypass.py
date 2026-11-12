"""Zero-bypass regression proof for the runtime orchestration seam."""
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from scripts.hive_orchestration import OrchestrationRejected, prepare_validated_research_task
from tests.test_hive_orchestration import CONFIG, EVIDENCE, SCHEMA, TASK, URL, extractor, fetcher


class ZeroBypassTests(unittest.TestCase):
    def test_policy_denial_has_zero_downstream_calls(self):
        researcher = Mock()
        auditor_a = Mock()
        auditor_b = Mock()
        queue_write = Mock()
        ledger_write = Mock()
        catalog_write = Mock()
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
        auditor_a.assert_not_called()
        auditor_b.assert_not_called()
        queue_write.assert_not_called()
        ledger_write.assert_not_called()
        catalog_write.assert_not_called()

    def test_candidate_rejection_has_zero_auditor_calls(self):
        researcher = Mock(return_value="{}")
        auditor_a = Mock()
        auditor_b = Mock()
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
        auditor_a.assert_not_called()
        auditor_b.assert_not_called()

    def test_valid_path_does_not_auto_publish(self):
        researcher = Mock(return_value=json.dumps({
            "identity": {"make": "Synthetic", "model": "Model X"},
            "performance": {"power_w": 110000},
            "provenance": {
                "sources": [{"source_id": "oem-1", "url": URL}],
                "claim_evidence": [{
                    "claim_path": "performance.power_w",
                    "source_id": "oem-1",
                    "locator": "document",
                    "quote": "Official technical specification.",
                }],
            },
        }))
        result = prepare_validated_research_task(
            reserved_task=TASK,
            schema=SCHEMA,
            config=CONFIG,
            fetcher=fetcher,
            extractor=extractor,
            researcher=researcher,
            today=date(2026, 11, 12),
        )
        self.assertIsNotNone(result.candidate)
        # Publication is deliberately outside this seam and requires both
        # independent auditor PASS verdicts plus human review.


if __name__ == "__main__":
    unittest.main()
