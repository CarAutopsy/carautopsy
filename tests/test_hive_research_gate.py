import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "autonomous_pipeline.py"
sys.path.insert(0, str(ROOT / "scripts"))

from hive_research_gate import PAUSE_REASON, ResearchPaused, require_verified_retrieval


SITECUSTOMIZE = r"""
import os
import sys
import types

# A provider invocation leaves a marker. The fail-closed test supplies a key,
# so this catches accidental calls instead of passing because credentials are absent.
try:
    import requests
    def forbidden_provider_call(*args, **kwargs):
        marker = os.environ.get("HIVE_PROVIDER_CALL_MARKER")
        if marker:
            with open(marker, "a", encoding="utf-8") as handle:
                handle.write("called\\n")
        raise AssertionError("provider call reached in safety-gate test")
    requests.post = forbidden_provider_call
except ImportError:
    pass

if os.environ.get("HIVE_TCO_ROUTE_PROBE") == "1":
    tco = types.ModuleType("tco_engine")
    def reached_tco_config(*args, **kwargs):
        raise RuntimeError("TCO_ROUTE_REACHED")
    tco.load_country_config = reached_tco_config
    tco.assert_tax_pack_publishable = lambda *args, **kwargs: None
    tco.calculate_tco = lambda *args, **kwargs: None
    sys.modules["tco_engine"] = tco
"""


class ResearchOnlySafetyGateTests(unittest.TestCase):
    """Exercise the real entry point and retain focused guard unit tests."""

    def _sandbox(self, root, extra_env=None):
        root.mkdir(parents=True, exist_ok=True)
        (root / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": os.pathsep.join((str(root), str(ROOT / "scripts"))),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        env.pop("DEEPSEEK_API_KEY", None)
        env.pop("DEEPSEEK_API_CARAUTOPSY_KEY", None)
        env.pop("GEMINI_API_KEY", None)
        env.pop("QWEN_API_KEY", None)
        if extra_env:
            env.update(extra_env)
        return env

    def _run_pipeline(self, cwd, args, env):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def _tree_hashes(self, root):
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

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

    def test_research_only_subprocess_pauses_without_provider_calls_or_state_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            (sandbox / "tasks").mkdir()
            (sandbox / "hive" / "state").mkdir(parents=True)
            (sandbox / "tasks" / "queue.json").write_text(
                json.dumps([{"variant_id": "fixture-vehicle", "make": "Fixture", "model": "Vehicle"}]),
                encoding="utf-8",
            )
            (sandbox / "tasks" / "failed.json").write_text("[]\n", encoding="utf-8")
            (sandbox / "hive" / "state" / "state.json").write_text('{"attempts": 0}\n', encoding="utf-8")
            provider_marker = sandbox / "provider-called.marker"
            env = self._sandbox(sandbox, {
                "QWEN_API_KEY": "test-key-not-a-real-secret",
                "HIVE_PROVIDER_CALL_MARKER": str(provider_marker),
            })
            before = self._tree_hashes(sandbox)

            result = self._run_pipeline(sandbox, ["--research-only"], env)

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("HIVE_RESEARCH_PAUSED:", result.stderr)
            self.assertFalse(provider_marker.exists(), "a provider was called before the pause")
            self.assertEqual(self._tree_hashes(sandbox), before, "the paused run mutated fixture state")

    def test_provider_smoke_test_keeps_its_own_route(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            env = self._sandbox(sandbox)
            result = self._run_pipeline(sandbox, ["--provider-smoke-test"], env)
            self.assertIn("PROVIDER_SMOKE_TEST=", result.stdout)
            self.assertNotIn("HIVE_RESEARCH_PAUSED", result.stdout + result.stderr)
            self.assertNotEqual(result.returncode, 2)

    def test_full_tco_route_bypasses_research_pause_without_dispatching_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            (sandbox / "tasks").mkdir()
            queue = sandbox / "tasks" / "queue.json"
            queue.write_text(
                json.dumps([{"variant_id": "fixture-vehicle", "make": "Fixture", "model": "Vehicle"}]),
                encoding="utf-8",
            )
            provider_marker = sandbox / "provider-called.marker"
            env = self._sandbox(sandbox, {
                "HIVE_TCO_ROUTE_PROBE": "1",
                "QWEN_API_KEY": "test-key-not-a-real-secret",
                "HIVE_PROVIDER_CALL_MARKER": str(provider_marker),
            })
            before = hashlib.sha256(queue.read_bytes()).hexdigest()
            result = self._run_pipeline(sandbox, [], env)
            self.assertIn("TCO_ROUTE_REACHED", result.stderr)
            self.assertNotIn("HIVE_RESEARCH_PAUSED", result.stdout + result.stderr)
            self.assertFalse(provider_marker.exists(), "full TCO mode must not dispatch research providers")
            self.assertEqual(hashlib.sha256(queue.read_bytes()).hexdigest(), before)

    def test_gate_ordering_remains_a_secondary_static_guard(self):
        source = SCRIPT.read_text(encoding="utf-8")
        gate = source.index("require_verified_retrieval(VERIFIED_RETRIEVAL_AVAILABLE)")
        batch_bound = source.index("RESEARCH_BATCH_SIZE = bounded_batch_size")
        self.assertLess(batch_bound, gate)
        manifest = source.index("HIVE_SOURCE_POLICY = load_policy()")
        coverage = source.index("require_variant_coverage(HIVE_SOURCE_POLICY, upcoming_ids)")
        evidence_prefetch = source.index("evidence = retrieve_approved_evidence(")
        evidence_validation = source.index("HIVE_PREFETCHED_EVIDENCE[variant_id] = validate_evidence_bundle(evidence)")
        proposal_checkout = source.index('run(["git", "checkout", "-B", open_research_pr["headRefName"], proposal_head_sha])')
        state_overlay = source.index("load_state(ROOT)")
        self.assertGreater(manifest, gate)
        self.assertGreater(coverage, manifest)
        self.assertLess(evidence_prefetch, evidence_validation)
        self.assertLess(evidence_validation, proposal_checkout)
        self.assertLess(evidence_validation, state_overlay)
        for operation in (
            "run_hive_research_and_audit(",
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
