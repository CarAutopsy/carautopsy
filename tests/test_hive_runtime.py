"""Runtime integration tests; all provider and auditor interactions are mocked."""
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
        "sources": [{"source_id": "oem-1", "url": "https://oem.example/specs/model.html"}],
        "claim_evidence": [{
            "claim_path": "performance.power_w",
            "source_id": "oem-1",
            "locator": "document",
            "quote": "Official technical specification.",
        }],
    },
}


class RuntimeResearchPathTests(unittest.TestCase):
    def test_valid_path_requires_two_pass_verdicts(self):
        researcher = Mock(return_value=json.dumps(VALID_CANDIDATE))
        auditor_a = Mock(return_value="PASS")
        auditor_b = Mock(return_value="PASS")
        result = run_hive_research_path(
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
        self.assertFalse(result["published"])
        self.assertEqual(result["auditor_a_verdict"], "PASS")
        self.assertEqual(result["auditor_b_verdict"], "PASS")
        auditor_a.assert_called_once()
        auditor_b.assert_called_once()

    def test_auditor_failure_is_distinct_from_provenance_rejection(self):
        researcher = Mock(return_value=json.dumps(VALID_CANDIDATE))
        auditor_a = Mock(return_value="PASS")
        auditor_b = Mock(return_value="FAIL")
        with self.assertRaises(AuditorFailure):
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

    def test_auditor_exception_is_distinct_from_provenance_rejection(self):
        researcher = Mock(return_value=json.dumps(VALID_CANDIDATE))
        auditor_a = Mock(return_value="PASS")
        auditor_b = Mock(side_effect=RuntimeError("auditor down"))
        with self.assertRaises(AuditorFailure):
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

    def test_policy_denial_stops_before_auditors(self):
        researcher = Mock()
        auditor_a = Mock()
        auditor_b = Mock()
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

    def test_candidate_rejection_stops_before_auditors(self):
        researcher = Mock(return_value="{}")
        auditor_a = Mock()
        auditor_b = Mock()
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

    def test_both_auditors_receive_equivalent_inputs(self):
        researcher = Mock(return_value=json.dumps(VALID_CANDIDATE))
        auditor_a = Mock(return_value="PASS")
        auditor_b = Mock(return_value="PASS")
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
        args_a, _ = auditor_a.call_args
        args_b, _ = auditor_b.call_args
        self.assertEqual(args_a, args_b)


if __name__ == "__main__":
    unittest.main()
