"""Retry and restart paths must re-enter the same zero-bypass runtime path."""
import unittest
from datetime import date
from unittest.mock import Mock

from scripts.hive_runtime import RuntimeResearchRejected, run_hive_research_path
from tests.test_hive_runtime import CONFIG, SCHEMA, TASK, extractor, fetcher


class RuntimeRetryTests(unittest.TestCase):
    def test_retry_cannot_skip_policy_gate(self):
        researcher = Mock()
        auditor_a = Mock()
        auditor_b = Mock()
        for _ in range(2):
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
        self.assertEqual(researcher.call_count, 0)
        self.assertEqual(auditor_a.call_count, 0)
        self.assertEqual(auditor_b.call_count, 0)

    def test_restart_cannot_skip_candidate_gate(self):
        researcher = Mock(return_value="{}")
        auditor_a = Mock()
        auditor_b = Mock()
        for _ in range(2):
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
        self.assertEqual(researcher.call_count, 2)
        self.assertEqual(auditor_a.call_count, 0)
        self.assertEqual(auditor_b.call_count, 0)


if __name__ == "__main__":
    unittest.main()
