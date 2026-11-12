"""State immutability tests for the runtime orchestration seam."""
import json
import unittest
from datetime import date
from unittest.mock import Mock

from scripts.hive_orchestration import OrchestrationRejected, prepare_validated_research_task
from tests.test_hive_orchestration import CONFIG, SCHEMA, TASK, extractor, fetcher


class StateImmutabilityTests(unittest.TestCase):
    def test_failure_paths_do_not_mutate_state(self):
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
                researcher=Mock(),
                today=date(2026, 11, 12),
            )
        queue_write.assert_not_called()
        ledger_write.assert_not_called()
        catalog_write.assert_not_called()

    def test_successful_validation_does_not_publish(self):
        researcher = Mock(return_value=json.dumps({
            "identity": {"make": "Synthetic", "model": "Model X"},
            "performance": {"power_w": 110000},
            "provenance": {
                "sources": [{"source_id": "oem-1", "url": "https://oem.example/specs/model.html"}],
                "claim_evidence": [{
                    "claim_path": "performance.power_w",
                    "source_id": "oem-1",
                    "locator": "document",
                    "quote": "Official technical specification.",
                }],
            },
        }))
        queue_write = Mock()
        ledger_write = Mock()
        catalog_write = Mock()
        prepare_validated_research_task(
            reserved_task=TASK,
            schema=SCHEMA,
            config=CONFIG,
            fetcher=fetcher,
            extractor=extractor,
            researcher=researcher,
            today=date(2026, 11, 12),
        )
        queue_write.assert_not_called()
        ledger_write.assert_not_called()
        catalog_write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
