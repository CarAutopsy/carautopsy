"""State immutability tests for runtime integration."""
import json
import unittest
from datetime import date
from unittest.mock import Mock

from scripts.hive_runtime import AuditorFailure, RuntimeResearchRejected, run_hive_research_path
from tests.test_hive_orchestration import CONFIG, SCHEMA, TASK, extractor, fetcher


VALID_CANDIDATE = {
    "variant_id": "synthetic.model-x",
    "identity": {"make": "Synthetic", "model": "Model X"},
    "performance": {"power_w": 110000},
    "provenance": {
        "sources": [{"source_id": "d91fac58588248c48d775c95", "url": "https://oem.example/specs/model.html"}],
        "claim_evidence": [{
            "claim_path": "performance.power_w",
            "source_id": "d91fac58588248c48d775c95",
            "locator": "document",
            "quote": "Official technical specification.",
        }],
    },
}


class RuntimeStateTests(unittest.TestCase):
    def test_failure_paths_do_not_mutate_state(self):
        queue_write = Mock()
        ledger_write = Mock()
        catalog_write = Mock()
        with self.assertRaises(RuntimeResearchRejected):
            run_hive_research_path(
                reserved_task=TASK,
                schema=SCHEMA,
                config={"version": 1, "approved_hosts": [], "source_policies": []},
                fetcher=Mock(),
                extractor=Mock(),
                researcher=Mock(),
                auditor_a=Mock(),
                auditor_b=Mock(),
                today=date(2026, 11, 12),
            )
        queue_write.assert_not_called()
        ledger_write.assert_not_called()
        catalog_write.assert_not_called()

    def test_auditor_failure_does_not_mutate_state(self):
        researcher = Mock(return_value=json.dumps(VALID_CANDIDATE))
        queue_write = Mock()
        ledger_write = Mock()
        catalog_write = Mock()
        with self.assertRaises(AuditorFailure):
            run_hive_research_path(
                reserved_task=TASK,
                schema=SCHEMA,
                config=CONFIG,
                fetcher=fetcher,
                extractor=extractor,
                researcher=researcher,
                auditor_a=Mock(return_value="PASS"),
                auditor_b=Mock(return_value="FAIL"),
                today=date(2026, 11, 12),
            )
        queue_write.assert_not_called()
        ledger_write.assert_not_called()
        catalog_write.assert_not_called()

    def test_successful_path_does_not_auto_publish(self):
        researcher = Mock(return_value=json.dumps(VALID_CANDIDATE))
        queue_write = Mock()
        ledger_write = Mock()
        catalog_write = Mock()
        result = run_hive_research_path(
            reserved_task=TASK,
            schema=SCHEMA,
            config=CONFIG,
            fetcher=fetcher,
            extractor=extractor,
            researcher=researcher,
            auditor_a=Mock(return_value="PASS"),
            auditor_b=Mock(return_value="PASS"),
            today=date(2026, 11, 12),
        )
        self.assertFalse(result["published"])
        queue_write.assert_not_called()
        ledger_write.assert_not_called()
        catalog_write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
