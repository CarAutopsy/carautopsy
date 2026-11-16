import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue_roadmap_controller import (
    IntakeControllerError,
    build_dry_run_report,
    fetch_issue_snapshots,
)


def issue(number, state, labels=None):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "labels": labels or [],
        "html_url": f"https://github.com/CarAutopsy/carautopsy/issues/{number}",
    }


class IssueCrawlerStateFilterTests(unittest.TestCase):
    def test_fetch_all_requests_all_states_and_keeps_closed_snapshots(self):
        response = Mock()
        response.links = {}
        response.json.return_value = [
            issue(10, "open", [{"name": "roadmap:candidate"}]),
            issue(11, "closed", [{"name": "roadmap:candidate"}]),
        ]
        session = Mock()
        session.get.return_value = response

        response.json.return_value[0]["updated_at"] = "2026-11-16T12:00:00Z"
        response.json.return_value[1]["updated_at"] = "2026-11-16T13:00:00Z"
        snapshots = fetch_issue_snapshots(
            "CarAutopsy/carautopsy", state="all", session=session
        )

        self.assertEqual([item["state"] for item in snapshots], ["open", "closed"])
        self.assertEqual(snapshots[1]["updated_at"], "2026-11-16T13:00:00Z")
        self.assertEqual(session.get.call_args.kwargs["params"]["state"], "all")
        report = build_dry_run_report(
            snapshots, repository="CarAutopsy/carautopsy", source="github-all-issues"
        )
        self.assertEqual(report["snapshot_classification_counts"], {
            "actionable": 1, "closed": 1
        })
        self.assertEqual(report["proposal_count"], 1)
        self.assertEqual(report["issue_snapshots"], [
            {"number": 10, "state": "open", "updated_at": "2026-11-16T12:00:00Z"},
            {"number": 11, "state": "closed", "updated_at": "2026-11-16T13:00:00Z"},
        ])

    def test_fetch_rejects_malformed_updated_at(self):
        response = Mock()
        response.links = {}
        response.json.return_value = [issue(14, "closed")]
        response.json.return_value[0]["updated_at"] = "not-a-timestamp"
        session = Mock()
        session.get.return_value = response
        with self.assertRaisesRegex(IntakeControllerError, "updated_at"):
            fetch_issue_snapshots("CarAutopsy/carautopsy", state="all", session=session)

    def test_fetch_closed_uses_closed_filter(self):
        response = Mock()
        response.links = {}
        response.json.return_value = [issue(12, "closed")]
        session = Mock()
        session.get.return_value = response

        snapshots = fetch_issue_snapshots(
            "CarAutopsy/carautopsy", state="closed", session=session
        )

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(session.get.call_args.kwargs["params"]["state"], "closed")

    def test_invalid_state_fails_before_network_access(self):
        session = Mock()
        with self.assertRaisesRegex(IntakeControllerError, "state must be"):
            fetch_issue_snapshots("CarAutopsy/carautopsy", state="merged", session=session)
        session.get.assert_not_called()

    def test_default_fetch_remains_open_only(self):
        response = Mock()
        response.links = {}
        response.json.return_value = [issue(13, "open")]
        session = Mock()
        session.get.return_value = response

        fetch_issue_snapshots("CarAutopsy/carautopsy", session=session)

        self.assertEqual(session.get.call_args.kwargs["params"]["state"], "open")


if __name__ == "__main__":
    unittest.main()
