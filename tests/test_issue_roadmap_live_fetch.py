import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue_roadmap_controller import (
    IntakeControllerError,
    build_reconciliation_dry_run_report,
    main,
)


def snapshot(number=10, state="open", labels=None):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "labels": labels if labels is not None else ["roadmap:candidate"],
        "html_url": f"https://github.com/CarAutopsy/carautopsy/issues/{number}",
    }


class LiveIssueFetchCliTests(unittest.TestCase):
    def run_live_cli(self, snapshots):
        output = io.StringIO()
        with patch("issue_roadmap_controller.fetch_issue_snapshots", return_value=snapshots) as fetch:
            with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(["--fetch-github"]), 0)
        fetch.assert_called_once_with("CarAutopsy/carautopsy", "test-token", state="open")
        return output.getvalue()

    def test_live_fetch_cli_is_deterministic_and_uses_projected_metadata(self):
        snapshots = [snapshot(11), snapshot(10, labels=[])]
        first = self.run_live_cli(snapshots)
        second = self.run_live_cli(snapshots)
        self.assertEqual(first, second)
        report = json.loads(first)
        self.assertEqual(report["source"], "github-open-issues")
        self.assertEqual(report["issue_snapshots_seen"], 2)
        self.assertEqual(report["proposal_count"], 2)
        self.assertFalse(report["roadmap_modified"])
        self.assertFalse(report["github_modified"])
        self.assertFalse(report["task_dispatch_performed"])
        self.assertNotIn("body", first)

    def test_live_fetch_cli_handles_closed_and_reopened_snapshots_fail_closed(self):
        closed = json.loads(self.run_live_cli([snapshot(12, state="closed")]))
        reopened = json.loads(self.run_live_cli([snapshot(12, state="open")]))
        self.assertEqual(closed["snapshot_classification_counts"], {"closed": 1})
        self.assertEqual(closed["proposal_count"], 0)
        self.assertEqual(reopened["snapshot_classification_counts"], {"actionable": 1})
        self.assertEqual(reopened["proposal_count"], 1)

    def test_live_fetch_cli_handles_empty_repository_response(self):
        report = json.loads(self.run_live_cli([]))
        self.assertEqual(report["issue_snapshots_seen"], 0)
        self.assertEqual(report["proposal_count"], 0)
        self.assertEqual(report["snapshot_classification_counts"], {})

    def test_live_fetch_cli_fails_closed_on_malformed_api_response(self):
        stderr = io.StringIO()
        with patch(
            "issue_roadmap_controller.fetch_issue_snapshots",
            side_effect=IntakeControllerError("GitHub issues endpoint returned a non-list payload"),
        ):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main(["--fetch-github"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("GitHub issues endpoint returned a non-list payload", stderr.getvalue())
        self.assertNotIn("test-token", stderr.getvalue())

    def test_reconciliation_marks_outdated_issue_snapshot_stale(self):
        report = build_reconciliation_dry_run_report({
            "repository": "CarAutopsy/carautopsy",
            "roadmap_tasks": [{
                "task_key": "issue-10",
                "issue_number": 10,
                "status": "approved",
                "dependencies": [],
                "source_updated_at": "2026-11-15T12:00:00Z",
            }],
            "issue_snapshots": [{
                "number": 10,
                "state": "open",
                "updated_at": "2026-11-16T12:00:00Z",
            }],
            "pull_request_evidence": [],
            "check_runs": [],
        })
        self.assertTrue(report["unchanged"][0]["stale"])
        self.assertEqual(report["proposals"], [])


if __name__ == "__main__":
    unittest.main()
