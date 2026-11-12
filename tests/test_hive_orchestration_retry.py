"""Retry and restart paths must re-enter the same zero-bypass seam."""
import json
import unittest
from datetime import date
from unittest.mock import Mock

from scripts.hive_orchestration import OrchestrationRejected, prepare_validated_research_task
from tests.test_hive_orchestration import CONFIG, SCHEMA, TASK, extractor, fetcher


class RetryRestartTests(unittest.TestCase):
    def test_retry_cannot_skip_policy_gate(self):
        researcher = Mock()
        for _ in range(2):
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
        self.assertEqual(researcher.call_count, 0)

    def test_restart_cannot_skip_candidate_gate(self):
        researcher = Mock(return_value="{}")
        for _ in range(2):
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
        self.assertEqual(researcher.call_count, 2)


if __name__ == "__main__":
    unittest.main()
