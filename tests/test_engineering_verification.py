"""Offline tests for the engineering-agent verification runner (issue #114)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from engineering_task import snapshot_digest, snapshot_manifest, validate_task_contract  # noqa: E402
from engineering_verification import (  # noqa: E402
    CHECK_REGISTRY,
    DEFAULT_CHECKS,
    MAX_OUTPUT_BYTES,
    TIMEOUT_EXIT_CODE,
    VerificationError,
    _Completed,
    assert_offline_command_registry,
    assert_offline_evidence,
    correction_feedback,
    parse_test_counts,
    redact_output,
    run_verification,
    scrub_environment,
    validate_check_names,
    verify_evidence_digest,
)


TARGET = "tests/fixtures/example.json"
# Test-only check: deliberately absent from the production CHECK_REGISTRY so a
# production caller cannot select a no-op check and get passed=True evidence.
TEST_ONLY_CHECK = {"python_probe": ("python", "--version")}
BASE = {
    "task_id": "eng-verify-001",
    "repository": "CarAutopsy/carautopsy",
    "base_sha": "a" * 40,
    "allowed_paths": [TARGET],
    "goal": "Verify a bounded change",
    "acceptance_criteria": ["tests pass"],
    "max_patch_bytes": 1000,
    "max_files_touched": 2,
    "timeout_seconds": 60,
    "max_provider_calls": 2,
    "max_spend_units": 0,
    "requires_owner_approval": True,
}
PATCH_DIGEST = "d" * 64


class _FakeRunner:
    """Records call arguments and returns a queued or computed result."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if callable(self.result):
            return self.result(argv, kwargs)
        return self.result


class EngineeringVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        target = self.root / TARGET
        target.parent.mkdir(parents=True)
        target.write_text('{"ok": true}\n', encoding="utf-8")
        self.contract = validate_task_contract(BASE)
        self.manifest = snapshot_manifest(self.root, self.contract["allowed_paths"])

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, runner, **overrides):
        options = {
            "contract": self.contract,
            "manifest": self.manifest,
            "patch_digest": PATCH_DIGEST,
            "root": self.root,
            "runner": runner,
            "status_probe": lambda _root: "",
        }
        options.update(overrides)
        return run_verification(**options)

    def test_command_registry_is_offline_and_has_no_noop_check(self):
        assert_offline_command_registry()
        self.assertNotIn("python_probe", CHECK_REGISTRY)
        with patch.dict(CHECK_REGISTRY, {"python_probe": ("python", "-c", "print(1)")}):
            with self.assertRaises(VerificationError):
                assert_offline_command_registry()
        with patch.dict(CHECK_REGISTRY, TEST_ONLY_CHECK):
            with self.assertRaises(VerificationError):
                validate_check_names(["python_probe", "python_probe"])

    def test_check_names_fail_closed(self):
        for names in ("unit_tests", [], ["unknown"], ["unit_tests", "unit_tests"],
                      ["unit_tests"] * 11, [1]):
            with self.subTest(names=names):
                with self.assertRaises(VerificationError):
                    validate_check_names(names)
        self.assertEqual(validate_check_names(DEFAULT_CHECKS), DEFAULT_CHECKS)

    def test_environment_is_scrubbed(self):
        source = {
            "PATH": "/bin",
            "SystemRoot": "C:\\Windows",
            "GITHUB_TOKEN": "secret-token",
            "OPENAI_API_KEY": "secret-key",
            "MY_PASSWORD": "secret-password",
        }
        environment = scrub_environment(source)
        self.assertEqual(environment["PATH"], "/bin")
        self.assertEqual(environment["SystemRoot"], "C:\\Windows")
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        self.assertEqual(environment["PIP_NO_INDEX"], "1")
        for name in ("GITHUB_TOKEN", "OPENAI_API_KEY", "MY_PASSWORD"):
            self.assertNotIn(name, environment)

    def test_successful_run_emits_stable_offline_evidence(self):
        runner = _FakeRunner(_Completed(0, b"Ran 2 tests in 0.01s\n\nOK\n", b""))
        first = self._run(runner)
        second = self._run(runner)
        self.assertEqual(first, second)
        self.assertTrue(first["passed"])
        self.assertEqual([item["name"] for item in first["checks"]], list(DEFAULT_CHECKS))
        self.assertEqual(first["checks"][0]["test_counts"]["tests_run"], 2)
        self.assertTrue(first["checks"][0]["test_counts"]["passed"])
        self.assertEqual(first["snapshot_digest"], snapshot_digest(self.manifest))
        self.assertEqual(len(first["evidence_digest"]), 64)
        self.assertEqual(first["provider_calls"], 0)
        self.assertEqual(first["live_source_requests"], 0)
        self.assertFalse(first["runtime_isolation_demonstrated"])
        self.assertFalse(first["execution_enabled"])
        self.assertFalse(first["draft_pr_created"])
        self.assertTrue(first["requires_owner_approval"])
        verify_evidence_digest(first)
        assert_offline_evidence(first)
        self.assertEqual(correction_feedback(first), "")
        for argv, kwargs in runner.calls:
            self.assertTrue(argv[0].endswith("python") or "python" in argv[0])
            self.assertNotIn("GITHUB_TOKEN", kwargs["env"])
            self.assertEqual(kwargs["timeout"], 60)

    def test_failure_feedback_is_bounded_and_redacted(self):
        output = b"FAILED (failures=1)\nGITHUB_TOKEN=abc123secret\n"
        artifact = self._run(_FakeRunner(_Completed(1, output, b"error detail\n")))
        self.assertFalse(artifact["passed"])
        excerpt = artifact["checks"][0]["output_excerpt"]
        self.assertIn("[REDACTED]", excerpt)
        self.assertNotIn("abc123secret", excerpt)
        feedback = correction_feedback(artifact)
        self.assertIn("exit code 1", feedback)
        self.assertIn("unit_tests", feedback)
        self.assertLessEqual(len(feedback), 2000)
        self.assertEqual(feedback, correction_feedback(artifact))

    def test_timeout_and_execution_error_are_recorded(self):
        timed_out = self._run(_FakeRunner(_Completed(
            TIMEOUT_EXIT_CODE, b"", b"", timed_out=True
        )))
        self.assertIn("timeout", correction_feedback(timed_out))
        failed_start = self._run(_FakeRunner(_Completed(
            126, b"", b"", execution_error=True
        )))
        self.assertIn("execution error", correction_feedback(failed_start))

    def test_output_is_bounded_and_digested(self):
        huge = b"x" * (MAX_OUTPUT_BYTES + 500)
        artifact = self._run(_FakeRunner(_Completed(1, huge, b"")))
        record = artifact["checks"][0]
        self.assertTrue(record["output_truncated"])
        self.assertEqual(len(record["stdout_sha256"]), 64)
        self.assertLessEqual(len(record["output_excerpt"]), 2000)

    def test_snapshot_changes_fail_closed(self):
        def mutate(_argv, _kwargs):
            (self.root / TARGET).write_text('{"ok": false}\n', encoding="utf-8")
            return _Completed(0, b"OK\n", b"")

        with self.assertRaisesRegex(VerificationError, "snapshot changed"):
            self._run(_FakeRunner(mutate))

        with self.assertRaisesRegex(VerificationError, "does not match the checkout"):
            self._run(_FakeRunner(_Completed(0)), manifest={TARGET: "f" * 64})

    def test_noop_check_cannot_be_selected_by_a_production_caller(self):
        with self.assertRaisesRegex(VerificationError, "unknown verification check"):
            self._run(_FakeRunner(_Completed(0)), check_names=("python_probe",))

    def test_real_subprocess_probe_is_offline_and_deterministic(self):
        with patch.dict(CHECK_REGISTRY, TEST_ONLY_CHECK):
            first = self._run(None, check_names=("python_probe",))
            second = self._run(None, check_names=("python_probe",))
        self.assertTrue(first["passed"])
        self.assertEqual(first, second)
        assert_offline_evidence(first)

    def test_working_tree_integrity_is_reported_and_enforced(self):
        artifact = self._run(_FakeRunner(_Completed(0, b"OK\n", b"")))
        self.assertTrue(artifact["working_tree_intact"])
        self.assertEqual(artifact["snapshot_intact_scope"], "allowed_paths")
        self.assertIn("git status", artifact["working_tree_scope"])
        assert_offline_evidence(artifact)
        for tampered in (
            dict(artifact, working_tree_intact=False),
            dict(artifact, snapshot_intact_scope="entire checkout"),
        ):
            with self.subTest(tampered=tampered):
                with self.assertRaises(VerificationError):
                    assert_offline_evidence(tampered)

    def test_dirty_working_tree_fails_before_any_check(self):
        runner = _FakeRunner(_Completed(0))
        with self.assertRaisesRegex(VerificationError, "working tree is not clean"):
            self._run(runner, status_probe=lambda _root: " M scripts/example.py")
        self.assertEqual(runner.calls, [])

    def test_working_tree_change_during_check_fails_closed(self):
        states = iter(["", " M scripts/example.py"])

        def changing_status(_root):
            return next(states)

        with self.assertRaisesRegex(VerificationError, "working tree changed"):
            self._run(_FakeRunner(_Completed(0, b"OK\n", b"")), status_probe=changing_status)

    def test_evidence_tampering_is_rejected(self):
        artifact = self._run(_FakeRunner(_Completed(0, b"OK\n", b"")))
        altered = dict(artifact, provider_calls=1)
        with self.assertRaises(VerificationError):
            assert_offline_evidence(altered)
        altered = dict(artifact, passed=False)
        with self.assertRaises(VerificationError):
            verify_evidence_digest(altered)

    def test_invalid_inputs_fail_closed(self):
        runner = _FakeRunner(_Completed(0))
        with self.assertRaises(VerificationError):
            self._run(runner, patch_digest="not-a-digest")
        with self.assertRaises(VerificationError):
            self._run(runner, root=self.root / "missing")
        with self.assertRaises(VerificationError):
            self._run(runner, contract=dict(self.contract, timeout_seconds=0))

    def test_test_count_parsing_is_conservative(self):
        self.assertEqual(parse_test_counts("Ran 7 tests in 0.2s\n\nOK\n"), {
            "tests_run": 7, "failures": 0, "errors": 0, "passed": True,
        })
        self.assertEqual(parse_test_counts("Ran 7 tests\nFAILED (failures=2, errors=1)"), {
            "tests_run": 7, "failures": 2, "errors": 1, "passed": False,
        })
        self.assertEqual(parse_test_counts("")["tests_run"], None)

    def test_output_redaction_is_applied_to_secret_shapes(self):
        text = "ghp_abcdefghijklmnopqrstuvwxyz\nall good\n"
        self.assertEqual(redact_output(text), "[REDACTED]\nall good")


if __name__ == "__main__":
    unittest.main()
