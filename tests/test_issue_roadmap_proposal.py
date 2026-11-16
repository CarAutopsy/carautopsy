import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from issue_roadmap_proposal import (
    ProposalArtifactError,
    build_proposal_artifact,
    render_proposal_artifact_json,
    render_proposal_comment,
)


SHA_HEAD = "a" * 40


def approved_report():
    return {
        "schema_version": 1,
        "mode": "proposal-only",
        "roadmap_modified": False,
        "github_modified": False,
        "task_dispatch_performed": False,
        "proposals": [
            {
                "task_key": "issue-10",
                "issue_number": 10,
                "from_status": "approved",
                "to_status": "done",
                "requires_owner_approval": False,
                "evidence": {
                    "issue_number": 10,
                    "linked_pr_number": 110,
                    "head_sha": SHA_HEAD,
                },
            }
        ],
        "unchanged": [],
    }


class RoadmapProposalArtifactTests(unittest.TestCase):
    def test_artifact_id_and_markdown_are_deterministic(self):
        report = approved_report()
        before = copy.deepcopy(report)
        first = build_proposal_artifact(report)
        second = build_proposal_artifact(report)
        self.assertEqual(first, second)
        self.assertTrue(first["proposal_id"].startswith("sha256:"))
        self.assertIn("No roadmap, GitHub, workflow, or task-queue changes were applied", first["comment_markdown"])
        self.assertIn("PR | Exact head", first["comment_markdown"])
        self.assertEqual(report, before)

    def test_proposals_are_sorted_by_stable_task_key(self):
        report = approved_report()
        other = copy.deepcopy(report["proposals"][0])
        other["task_key"] = "issue-09"
        other["issue_number"] = 9
        other["evidence"]["issue_number"] = 9
        report["proposals"].insert(0, other)
        artifact = build_proposal_artifact(report)
        self.assertLess(
            artifact["report"]["proposals"][0]["task_key"],
            artifact["report"]["proposals"][1]["task_key"],
        )

    def test_pending_owner_decision_is_rendered_without_claiming_approval(self):
        report = approved_report()
        report["proposals"] = []
        report["unchanged"] = [{
            "task_key": "issue-10",
            "status": "approved",
            "proposed_status": "done",
            "requires_owner_approval": True,
            "reason": "status change requires explicit owner approval",
        }]
        markdown = render_proposal_comment(report)
        self.assertIn("Pending owner approval", markdown)
        self.assertIn("issue-10", markdown)
        self.assertIn("owner approval required", markdown)

    def test_untrusted_reason_text_is_html_escaped(self):
        report = approved_report()
        report["proposals"] = []
        report["unchanged"] = [{
            "task_key": "issue-10",
            "status": "approved",
            "reason": "<script>alert('x')</script>",
        }]
        markdown = render_proposal_comment(report)
        self.assertNotIn("<script>", markdown)
        self.assertIn("&lt;script&gt;", markdown)

    def test_artifact_json_is_stable_and_contains_report_hash(self):
        report = approved_report()
        first = render_proposal_artifact_json(report)
        second = render_proposal_artifact_json(report)
        self.assertEqual(first, second)
        parsed = json.loads(first)
        self.assertEqual(parsed["report"], report)
        self.assertTrue(parsed["proposal_id"].startswith("sha256:"))

    def test_rejects_non_proposal_or_write_enabled_reports(self):
        for key, value in (
            ("mode", "apply"),
            ("roadmap_modified", True),
            ("github_modified", True),
            ("task_dispatch_performed", True),
            ("schema_version", True),
        ):
            report = approved_report()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(ProposalArtifactError):
                build_proposal_artifact(report)

    def test_rejects_malformed_or_unverified_status_evidence(self):
        for mutate in (
            lambda r: r["proposals"][0]["evidence"].update({"head_sha": "bad"}),
            lambda r: r["proposals"][0]["evidence"].update({"issue_number": True}),
            lambda r: r["proposals"][0]["evidence"].update({"linked_pr_number": True}),
            lambda r: r["proposals"][0].update({"requires_owner_approval": True}),
            lambda r: r["proposals"][0].update({"to_status": "activated"}),
        ):
            report = approved_report()
            mutate(report)
            with self.assertRaises(ProposalArtifactError):
                build_proposal_artifact(report)


if __name__ == "__main__":
    unittest.main()
