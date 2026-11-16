import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue_roadmap_controller import main


class IssueStateCliGuardTests(unittest.TestCase):
    def assert_rejected(self, arguments):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(arguments)
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--state is only valid with --fetch-github", stderr.getvalue())

    def test_explicit_open_state_is_rejected_for_issue_fixture(self):
        fixture = ROOT / "tests/fixtures/issue-intake.example.json"
        self.assert_rejected(["--input", str(fixture), "--state", "open"])

    def test_explicit_open_state_is_rejected_for_reconciliation_fixture(self):
        fixture = ROOT / "tests/fixtures/roadmap-reconciliation.example.json"
        self.assert_rejected(["--reconcile-input", str(fixture), "--state", "open"])


if __name__ == "__main__":
    unittest.main()
