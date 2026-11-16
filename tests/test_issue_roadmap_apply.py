import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue_roadmap_apply import (
    RoadmapApplyError,
    build_owner_approved_apply_plan,
    proposal_digest,
)


OWNER = "realarchitekt"
REPOSITORY = "CarAutopsy/carautopsy"
ROADMAP_SHA = "a" * 40
UPDATED_AT = "2026-11-16T20:00:00Z"


def report():
    return {
        "schema_version": 1,
        "mode": "dry-run",
        "repository": REPOSITORY,
        "source": "github-all-issues",
        "issue_snapshots_seen": 1,
        "api_records_seen": 1,
        "pull_request_snapshots_excluded": 0,
        "issue_snapshots": [
            {"number": 10, "state": "open", "updated_at": UPDATED_AT}
        ],
        "snapshot_classification_counts": {"actionable": 1},
        "proposal_count": 1,
        "actionable_proposal_count": 1,
        "owner_triage_count": 0,
        "requires_owner_approval": True,
        "roadmap_modified": False,
        "github_modified": False,
        "task_dispatch_performed": False,
        "proposals": [{
            "task_key": "issue-10",
            "issue_number": 10,
            "issue_url": "https://github.com/CarAutopsy/carautopsy/issues/10",
            "title": "Add safe issue intake",
            "classification": "actionable",
            "status": "proposed",
            "dependencies": [],
            "acceptance_criteria": [],
            "owner_actions": ["Supply criteria"],
            "owner_input_required": True,
            "requires_owner_approval": True,
        }],
    }


def approval_for(payload=None):
    payload = report() if payload is None else payload
    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "owner_login": OWNER,
        "proposal_id": proposal_digest(payload),
        "expected_roadmap_sha": ROADMAP_SHA,
        "approved_at": "2026-11-16T20:01:00Z",
        "confirmation": "APPLY ROADMAP PROPOSAL",
        "approved_tasks": [{
            "task_key": "issue-10",
            "issue_number": 10,
            "title": "Add safe issue intake",
            "dependencies": [],
            "acceptance_criteria": ["Reject malformed issue metadata"],
        }],
    }


def build(payload=None, approval=None, markdown="# Roadmap\n", sha=ROADMAP_SHA, owner=OWNER):
    payload = report() if payload is None else payload
    approval = approval_for(payload) if approval is None else approval
    return build_owner_approved_apply_plan(
        payload, approval, markdown, sha,
        repository=REPOSITORY, expected_owner_login=owner,
    )


class OwnerApprovedRoadmapApplyTests(unittest.TestCase):
    def test_builds_deterministic_plan_without_writing_roadmap(self):
        original = "# Roadmap\n"
        first = build(markdown=original)
        second = build(markdown=original)
        self.assertEqual(first, second)
        self.assertEqual(first["mode"], "apply-plan")
        self.assertEqual(first["changed_task_keys"], ["issue-10"])
        self.assertFalse(first["roadmap_modified"])
        self.assertEqual(original, "# Roadmap\n")
        self.assertIn("Owner-approved issue intake", first["roadmap_content"])
        self.assertIn("Reject malformed issue metadata", first["roadmap_content"])
        self.assertIn("issue-10", first["roadmap_content"])

    def test_same_proposal_is_idempotent_after_first_application(self):
        first = build()
        second = build(markdown=first["roadmap_content"], sha="b" * 40)
        self.assertEqual(second["mode"], "no-op-already-applied")
        self.assertEqual(second["changed_task_keys"], [])
        self.assertEqual(second["already_applied_task_keys"], ["issue-10"])
        self.assertEqual(second["roadmap_content"], first["roadmap_content"])

    def test_requires_configured_owner_identity(self):
        with self.assertRaisesRegex(RoadmapApplyError, "configured repository owner"):
            build(owner="someone-else")

    def test_rejects_stale_roadmap_sha(self):
        with self.assertRaisesRegex(RoadmapApplyError, "roadmap changed"):
            build(sha="b" * 40)

    def test_rejects_wrong_confirmation_phrase(self):
        approval = approval_for()
        approval["confirmation"] = "please apply"
        with self.assertRaisesRegex(RoadmapApplyError, "confirmation phrase"):
            build(approval=approval)

    def test_rejects_report_digest_mismatch(self):
        approval = approval_for()
        approval["proposal_id"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(RoadmapApplyError, "proposal ID"):
            build(approval=approval)

    def test_rejects_non_actionable_or_unlisted_issues(self):
        payload = report()
        payload["proposals"][0]["classification"] = "needs-owner-triage"
        approval = approval_for(payload)
        with self.assertRaisesRegex(RoadmapApplyError, "not an actionable"):
            build(payload, approval)

    def test_rejects_closed_issue_even_when_approval_exists(self):
        payload = report()
        payload["issue_snapshots"][0]["state"] = "closed"
        approval = approval_for(payload)
        with self.assertRaisesRegex(RoadmapApplyError, "open issue"):
            build(payload, approval)

    def test_requires_owner_supplied_acceptance_criteria(self):
        approval = approval_for()
        approval["approved_tasks"][0]["acceptance_criteria"] = []
        with self.assertRaisesRegex(RoadmapApplyError, "acceptance criteria"):
            build(approval=approval)

    def test_rejects_unknown_dependencies(self):
        approval = approval_for()
        approval["approved_tasks"][0]["dependencies"] = ["unknown-task"]
        with self.assertRaisesRegex(RoadmapApplyError, "unknown task key"):
            build(approval=approval)

    def test_rejects_duplicate_issue_snapshots(self):
        payload = report()
        payload["issue_snapshots"].append(copy.deepcopy(payload["issue_snapshots"][0]))
        approval = approval_for(payload)
        with self.assertRaisesRegex(RoadmapApplyError, "duplicate issue snapshots"):
            build(payload, approval)

    def test_rejects_inconsistent_managed_block_edit(self):
        first = build()
        altered = first["roadmap_content"].replace("Add safe issue intake", "Tampered title", 1)
        with self.assertRaisesRegex(RoadmapApplyError, "canonical task state"):
            build(markdown=altered, sha="b" * 40)


    def test_rejects_dependency_cycles(self):
        payload = report()
        payload["issue_snapshots"].append({
            "number": 11, "state": "open", "updated_at": UPDATED_AT
        })
        second = copy.deepcopy(payload["proposals"][0])
        second.update({
            "task_key": "issue-11",
            "issue_number": 11,
            "title": "Second approved task",
        })
        payload["proposals"].append(second)
        approval = approval_for(payload)
        approval["approved_tasks"] = [
            {
                "task_key": "issue-10",
                "issue_number": 10,
                "title": "Add safe issue intake",
                "dependencies": ["issue-11"],
                "acceptance_criteria": ["Reject malformed issue metadata"],
            },
            {
                "task_key": "issue-11",
                "issue_number": 11,
                "title": "Second approved task",
                "dependencies": ["issue-10"],
                "acceptance_criteria": ["Validate the second task"],
            },
        ]
        with self.assertRaisesRegex(RoadmapApplyError, "dependency graph"):
            build(payload, approval)

    def test_rejects_unexpected_report_fields(self):
        payload = report()
        payload["untrusted_extension"] = {"write": True}
        approval = approval_for(payload)
        with self.assertRaisesRegex(RoadmapApplyError, "read-only all-state"):
            build(payload, approval)

if __name__ == "__main__":
    unittest.main()
