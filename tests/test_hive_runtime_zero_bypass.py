"""Zero-bypass and zero-spend regression proof for runtime integration."""
import json
import unittest
from datetime import date
from unittest.mock import Mock

from scripts.hive_runtime import RuntimeResearchRejected, run_hive_research_path
from tests.test_hive_runtime import CONFIG, SCHEMA, TASK, VALID_CANDIDATE, extractor, fetcher


class RuntimeZeroBypassTests(unittest.TestCase):
    def test_policy_denial_has_zero_downstream_calls(self):
        researcher = Mock()
        auditor_a = Mock()
        auditor_b = Mock()
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
                researcher=researcher,
                auditor_a=auditor_a,
                auditor_b=auditor_b,
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
        queue_write = Mock()
        ledger_write = Mock()
        catalog_write = Mock()
        with self.assertRaises(RuntimeResearchRejected):
            run_hive_research_path(
                reserved_task=TASK,
                schema=SCHEMA,
                config=CONFIG,
                fetcher=fetcher,
                extractor=extractor,
                researcher=researcher,
                auditor_a=auditor_a,
                auditor_b=auditor_b,
                today=date(2026, 11, 12),
            )
        auditor_a.assert_not_called()
        auditor_b.assert_not_called()
        queue_write.assert_not_called()
        ledger_write.assert_not_called()
        catalog_write.assert_not_called()

    def test_no_publication_without_human_review(self):
        researcher = Mock(return_value=json.dumps(VALID_CANDIDATE))
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


if __name__ == "__main__":
    unittest.main()
