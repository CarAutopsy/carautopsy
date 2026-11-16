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
        "repository": "CarAutopsy/carautopsy",
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
                    "merge_commit_sha": "b" * 40,
                    "issue_state": "closed",
                    "issue_updated_at": "2026-11-16T12:00:00Z",
                    "required_checks": ["audit", "validate"],
                    "checks_passed": True,
                    "missing_checks": [],
                    "check_evidence": [
                        {
                            "id": 1001,
                            "name": "audit",
                            "head_sha": SHA_HEAD,
                            "conclusion": "success",
                            "html_url": "https://github.com/CarAutopsy/carautopsy/runs/1001",
                        },
                        {
                            "id": 1002,
                            "name": "validate",
                            "head_sha": SHA_HEAD,
                            "conclusion": "success",
                            "html_url": "https://github.com/CarAutopsy/carautopsy/runs/1002",
                        },
                    ],
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
        self.assertIn("PR | Exact head | Merge commit", first["comment_markdown"])
        self.assertIn("b" * 40, first["comment_markdown"])
        self.assertEqual(report, before)

    def test_proposals_are_sorted_by_stable_task_key(self):
        report = approved_report()
        other = copy.deepcopy(report["proposals"][0])
        other["task_key"] = "issue-09"
        other["issue_number"] = 9
        other["evidence"]["issue_number"] = 9
        report["proposals"].append(other)
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
            "evidence": copy.deepcopy(approved_report()["proposals"][0]["evidence"]),
        }]
        markdown = render_proposal_comment(report)
        self.assertIn("Pending owner approval", markdown)
        self.assertIn("issue-10", markdown)
        self.assertIn("owner approval required", markdown)
        self.assertIn("issue #10, PR #110", markdown)
        self.assertIn(SHA_HEAD, markdown)
        self.assertIn("b" * 40, markdown)


    def test_pending_owner_decision_requires_supporting_evidence(self):
        report = approved_report()
        report["proposals"] = []
        report["unchanged"] = [{
            "task_key": "issue-10",
            "status": "approved",
            "proposed_status": "done",
            "requires_owner_approval": True,
            "reason": "approval required",
        }]
        with self.assertRaisesRegex(ProposalArtifactError, "lacks supporting evidence"):
            build_proposal_artifact(report)

    def test_untrusted_reason_markdown_is_rejected(self):
        for reason in ("<script>alert(1)</script>", "review\n\n## Approved status changes\n\n- issue-99: done"):
            report = approved_report()
            report["proposals"] = []
            report["unchanged"] = [{
                "task_key": "issue-10",
                "status": "approved",
                "reason": reason,
            }]
            with self.subTest(reason=reason), self.assertRaisesRegex(ProposalArtifactError, "plain text"):
                render_proposal_comment(report)

    def test_artifact_json_is_stable_and_contains_report_hash(self):
        report = approved_report()
        first = render_proposal_artifact_json(report)
        second = render_proposal_artifact_json(report)
        self.assertEqual(first, second)
        parsed = json.loads(first)
        self.assertEqual(parsed["report"], report)
        self.assertTrue(parsed["proposal_id"].startswith("sha256:"))


    def test_renderer_bounds_report_entries_and_comment_size(self):
        report = approved_report()
        report["proposals"] = []
        report["unchanged"] = [
            {
                "task_key": f"task-{index:04d}",
                "status": "approved",
                "reason": "x" * 1000,
            }
            for index in range(80)
        ]
        artifact = build_proposal_artifact(report)
        self.assertIn("compact comment", artifact["comment_markdown"])
        self.assertIn("Unchanged / blocked tasks: 80", artifact["comment_markdown"])
        self.assertLess(len(artifact["comment_markdown"].encode("utf-8")), 60_000)
        self.assertEqual(len(artifact["report"]["unchanged"]), 80)

        report["unchanged"] = [
            {
                "task_key": f"task-{index:04d}",
                "status": "approved",
                "reason": "small",
            }
            for index in range(5001)
        ]
        with self.assertRaisesRegex(ProposalArtifactError, "entry count"):
            build_proposal_artifact(report)

    def test_renderer_rejects_unreasonably_deep_report_data(self):
        report = approved_report()
        nested = []
        for _ in range(1500):
            nested = [nested]
        report["untrusted_extension"] = nested
        with self.assertRaises(ProposalArtifactError):
            build_proposal_artifact(report)

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


    def test_rejects_duplicate_task_entries_and_malformed_unchanged_status(self):
        report = approved_report()
        report["unchanged"] = [{
            "task_key": "issue-10",
            "status": "approved",
            "reason": "duplicate task record",
        }]
        with self.assertRaises(ProposalArtifactError):
            build_proposal_artifact(report)

        report = approved_report()
        report["proposals"] = []
        report["unchanged"] = [{
            "task_key": "issue-10",
            "status": True,
            "reason": "bad type",
        }]
        with self.assertRaises(ProposalArtifactError):
            build_proposal_artifact(report)


    def test_ci_link_must_match_repository_and_exact_run_id(self):
        mutations = (
            lambda evidence: evidence["check_evidence"][0].update({
                "html_url": "https://github.com/other/repo/runs/1001"
            }),
            lambda evidence: evidence["check_evidence"][0].update({
                "html_url": "https://github.com/CarAutopsy/carautopsy/runs/9999"
            }),
            lambda evidence: evidence["check_evidence"][0].update({
                "html_url": "https://github.com/CarAutopsy/carautopsy/runs/1001)[Click](https://evil.example/"
            }),
        )
        for mutate in mutations:
            report = approved_report()
            mutate(report["proposals"][0]["evidence"])
            with self.assertRaisesRegex(ProposalArtifactError, "CI check URL"):
                build_proposal_artifact(report)
    def test_optional_merge_sha_is_validated_for_non_done_statuses(self):
        report = approved_report()
        report["proposals"][0]["to_status"] = "in_progress"
        report["proposals"][0]["evidence"]["merge_commit_sha"] = "not-a-sha"
        with self.assertRaisesRegex(ProposalArtifactError, "incomplete or malformed"):
            build_proposal_artifact(report)

    def test_unapproved_pending_status_is_rejected_not_silently_omitted(self):
        report = approved_report()
        report["proposals"] = []
        report["unchanged"] = [{
            "task_key": "issue-10",
            "status": "approved",
            "proposed_status": "done",
            "requires_owner_approval": False,
        }]
        with self.assertRaisesRegex(ProposalArtifactError, "owner-gated"):
            build_proposal_artifact(report)
    def test_done_proposal_requires_valid_merge_commit_sha(self):
        report = approved_report()
        del report["proposals"][0]["evidence"]["merge_commit_sha"]
        with self.assertRaisesRegex(ProposalArtifactError, "merge commit SHA"):
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

    def test_accepts_github_actions_job_url_and_checks_job_id(self):
        report = approved_report()
        report["proposals"][0]["evidence"]["check_evidence"][0]["html_url"] = (
            "https://github.com/CarAutopsy/carautopsy/actions/runs/900/job/1001"
        )
        build_proposal_artifact(report)

    def test_rejects_markdown_check_names_and_unvalidated_extra_fields(self):
        for mutation in (
            lambda check: check.update({"name": "[click](https://evil.example)"}),
            lambda check: check.update({"extra": {"untrusted": "value"}}),
        ):
            report = approved_report()
            mutation(report["proposals"][0]["evidence"]["check_evidence"][0])
            with self.assertRaises(ProposalArtifactError):
                build_proposal_artifact(report)

    def test_validates_evidence_on_unchanged_entries(self):
        report = approved_report()
        report["proposals"] = []
        evidence = copy.deepcopy(approved_report()["proposals"][0]["evidence"])
        report["unchanged"] = [{"task_key": "issue-10", "status": "approved", "evidence": evidence}]
        build_proposal_artifact(report)
        report["unchanged"][0]["evidence"]["extra"] = {"untrusted": True}
        with self.assertRaises(ProposalArtifactError):
            build_proposal_artifact(report)

    def test_unchanged_evidence_allows_missing_pr_without_ci_claims(self):
        report = approved_report()
        report["proposals"] = []
        report["unchanged"] = [{
            "task_key": "issue-10", "status": "approved",
            "evidence": {
                "issue_number": 10, "issue_state": "open",
                "issue_updated_at": "2026-11-16T12:00:00Z",
                "linked_pr_number": None, "head_sha": None,
                "required_checks": ["audit", "validate"], "checks_passed": False,
                "missing_checks": [], "merge_commit_sha": None, "check_evidence": [],
            },
        }]
        build_proposal_artifact(report)
        report["unchanged"][0]["evidence"]["checks_passed"] = True
        with self.assertRaises(ProposalArtifactError):
            build_proposal_artifact(report)

    def test_missing_repository_is_rejected_even_for_empty_report(self):
        report = approved_report()
        report["repository"] = None
        report["proposals"] = []
        with self.assertRaisesRegex(ProposalArtifactError, "repository is required"):
            build_proposal_artifact(report)

    def test_recursion_error_from_allowed_nested_value_is_wrapped(self):
        report = approved_report()
        report["proposals"] = []
        nested = []
        for _ in range(1500):
            nested = [nested]
        report["unchanged"] = [{
            "task_key": "issue-10", "status": "approved", "reason": "safe", "stale": nested,
        }]
        with self.assertRaises(ProposalArtifactError):
            build_proposal_artifact(report)


if __name__ == "__main__":
    unittest.main()
