import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hive_research_gate import PAUSE_REASON, ResearchPaused, require_verified_retrieval


class ResearchOnlySafetyGateTests(unittest.TestCase):
    """Verify the research-only pause is fail-closed and precedes side effects."""

    def test_unavailable_retrieval_raises_distinct_operational_pause(self):
        with self.assertRaises(ResearchPaused) as raised:
            require_verified_retrieval(False)
        self.assertEqual(raised.exception.exit_code, 2)
        self.assertIn("verified source retrieval is not available", str(raised.exception))

    def test_missing_or_unknown_readiness_fails_closed(self):
        for value in (None, 0, "", "false"):
            with self.subTest(value=value):
                with self.assertRaises(ResearchPaused):
                    require_verified_retrieval(value)

    def test_explicit_ready_state_allows_research_gate(self):
        self.assertIsNone(require_verified_retrieval(True))

    def test_gate_is_before_provider_and_durable_state_operations(self):
        source = (ROOT / "scripts" / "autonomous_pipeline.py").read_text(encoding="utf-8")
        gate = source.index("require_verified_retrieval(VERIFIED_RETRIEVAL_AVAILABLE)")
        for operation in (
            "raw, res_name, res_vendor = call_any(rp)",
            "audit_raw, audit_name = call_vendor(ap, audit_vendor)",
            "open_research_pr = get_open_research_pr() if RESEARCH_ONLY else None",
            "load_state(ROOT)",
            "curate_one(attempted_variant_ids if RESEARCH_ONLY else None)",
            "reconcile_with_pr(ROOT)",
            "save_state(ROOT",
            'run(["git", "checkout"',
            'run(["git", "commit"',
            'run(["git", "push"',
        ):
            with self.subTest(operation=operation):
                self.assertGreater(source.index(operation), gate)

    def test_pause_reason_does_not_classify_pause_as_vehicle_or_provider_failure(self):
        self.assertIn("research is paused", PAUSE_REASON)
        self.assertNotIn("provider failure", PAUSE_REASON)
        self.assertNotIn("audit failed", PAUSE_REASON)


if __name__ == "__main__":
    unittest.main()
