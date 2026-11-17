import json
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

    def test_issue_title_with_markdown_link_is_literal_and_reloadable(self):
        payload = report()
        payload["proposals"][0]["title"] = "[Review](https://example.com)"
        approval = approval_for(payload)
        approval["approved_tasks"][0]["title"] = payload["proposals"][0]["title"]
        first = build(payload, approval)
        data_end = first["roadmap_content"].index("\ncarautopsy-issue-roadmap:data:end -->")
        visible_table = first["roadmap_content"][data_end:]
        self.assertNotIn("[Review](https://example.com)", visible_table)
        self.assertIn("&#91;Review&#93;&#40;https://example.com&#41;", visible_table)
        data_start = first["roadmap_content"].index("<!-- carautopsy-issue-roadmap:data:start\n")
        stored_json = first["roadmap_content"][data_start + len("<!-- carautopsy-issue-roadmap:data:start\n"):data_end].strip()
        self.assertEqual(json.loads(stored_json)["tasks"][0]["title"], "[Review](https://example.com)")
        approval["expected_roadmap_sha"] = "b" * 40
        second = build(payload, approval, markdown=first["roadmap_content"], sha="b" * 40)
        self.assertEqual(second["mode"], "no-op-already-applied")

    def test_long_github_issue_title_up_to_256_chars_applies_and_reloads(self):
        payload = report()
        long_title = "T" * 250
        payload["proposals"][0]["title"] = long_title
        approval = approval_for(payload)
        approval["approved_tasks"][0]["title"] = long_title
        first = build(payload, approval)
        self.assertIn(long_title, first["roadmap_content"])
        approval["expected_roadmap_sha"] = "b" * 40
        second = build(payload, approval, markdown=first["roadmap_content"], sha="b" * 40)
        self.assertEqual(second["mode"], "no-op-already-applied")

    def test_duplicate_approved_task_keys_are_rejected(self):
        approval = approval_for()
        approval["approved_tasks"].append(copy.deepcopy(approval["approved_tasks"][0]))
        with self.assertRaisesRegex(RoadmapApplyError, "duplicated"):
            build(approval=approval)

    def test_rejects_malformed_issue_state_and_non_timezone_timestamp(self):
        for mutation in (
            lambda snapshot: snapshot.update({"state": "merged"}),
            lambda snapshot: snapshot.update({"updated_at": "2026-11-16T20:00:00"}),
        ):
            payload = report()
            mutation(payload["issue_snapshots"][0])
            approval = approval_for(payload)
            with self.assertRaisesRegex(RoadmapApplyError, "valid state and timezone-aware"):
                build(payload, approval)

    def test_current_open_snapshot_is_used_without_historical_state(self):
        payload = report()
        payload["issue_snapshots"] = [{"number": 10, "state": "open", "updated_at": UPDATED_AT}]
        approval = approval_for(payload)
        result = build(payload, approval)
        self.assertEqual(result["changed_task_keys"], ["issue-10"])

    def test_reordered_managed_markers_raise_roadmap_apply_error(self):
        first = build()
        content = first["roadmap_content"]
        data_start = content.index("<!-- carautopsy-issue-roadmap:data:start")
        block_start = content.index("<!-- carautopsy-issue-roadmap:start -->")
        malformed = content[:block_start] + content[data_start:] + content[block_start:data_start]
        with self.assertRaisesRegex(RoadmapApplyError, "markers are out of order"):
            build(markdown=malformed, sha="b" * 40)

    def test_managed_json_state_is_hidden_inside_one_html_comment(self):
        result = build()
        self.assertIn("<!-- carautopsy-issue-roadmap:data:start\n", result["roadmap_content"])
        self.assertIn("\ncarautopsy-issue-roadmap:data:end -->", result["roadmap_content"])
        data_start = result["roadmap_content"].index("<!-- carautopsy-issue-roadmap:data:start\n")
        data_end = result["roadmap_content"].index("\ncarautopsy-issue-roadmap:data:end -->")
        self.assertNotIn("-->", result["roadmap_content"][data_start:data_end])

    def test_partial_approval_batches_can_complete_one_report(self):
        payload = report()
        payload["issue_snapshots"].append({"number": 11, "state": "open", "updated_at": UPDATED_AT})
        second = copy.deepcopy(payload["proposals"][0])
        second.update({
            "task_key": "issue-11",
            "issue_number": 11,
            "issue_url": "https://github.com/CarAutopsy/carautopsy/issues/11",
            "title": "Add second safe intake task",
            "owner_actions": ["Confirm second task scope"],
        })
        payload["proposals"].append(second)
        payload["proposal_count"] = 2
        payload["actionable_proposal_count"] = 2
        approval = approval_for(payload)
        approval["approved_tasks"] = [approval["approved_tasks"][0]]
        first = build(payload, approval)
        self.assertEqual(first["changed_task_keys"], ["issue-10"])
        self.assertEqual([x["task_key"] for x in first["unresolved_owner_decisions"]], ["issue-11"])
        self.assertNotIn(approval["proposal_id"], first["roadmap_content"])

        partial_approval = copy.deepcopy(approval)
        partial_approval["expected_roadmap_sha"] = "b" * 40
        partial = build(
            payload, partial_approval,
            markdown=first["roadmap_content"], sha="b" * 40,
        )
        self.assertEqual(partial["mode"], "no-op-partially-applied")
        self.assertEqual(partial["changed_task_keys"], [])
        self.assertEqual([x["task_key"] for x in partial["unresolved_owner_decisions"]], ["issue-11"])

        second_approval = copy.deepcopy(approval)
        second_approval["expected_roadmap_sha"] = "c" * 40
        second_approval["approved_tasks"] = [{
            "task_key": "issue-11",
            "issue_number": 11,
            "title": "Add second safe intake task",
            "dependencies": [],
            "acceptance_criteria": ["Validate second intake"],
        }]
        completed = build(
            payload, second_approval,
            markdown=first["roadmap_content"], sha="c" * 40,
        )
        self.assertEqual(completed["changed_task_keys"], ["issue-11"])
        self.assertEqual(completed["unresolved_owner_decisions"], [])
        self.assertIn(approval["proposal_id"], completed["roadmap_content"])

    def test_renamed_unrelated_issue_does_not_block_another_approval(self):
        payload = report()
        payload["issue_snapshots"].append({"number": 11, "state": "open", "updated_at": UPDATED_AT})
        second = copy.deepcopy(payload["proposals"][0])
        second.update({
            "task_key": "issue-11",
            "issue_number": 11,
            "issue_url": "https://github.com/CarAutopsy/carautopsy/issues/11",
            "title": "Add second safe intake task",
            "owner_actions": ["Confirm second task scope"],
        })
        payload["proposals"].append(second)
        payload["proposal_count"] = 2
        payload["actionable_proposal_count"] = 2

        first_approval = approval_for(payload)
        first_approval["approved_tasks"] = [first_approval["approved_tasks"][0]]
        first = build(payload, first_approval)

        renamed = copy.deepcopy(payload)
        renamed["proposals"][0]["title"] = "Renamed safe issue intake"
        renamed["issue_snapshots"][0]["updated_at"] = "2026-11-16T20:05:00Z"
        second_approval = approval_for(renamed)
        second_approval["expected_roadmap_sha"] = "b" * 40
        second_approval["approved_tasks"] = [{
            "task_key": "issue-11",
            "issue_number": 11,
            "title": "Add second safe intake task",
            "dependencies": [],
            "acceptance_criteria": ["Validate second intake"],
        }]
        result = build(renamed, second_approval, markdown=first["roadmap_content"], sha="b" * 40)
        self.assertEqual(result["changed_task_keys"], ["issue-11"])
        self.assertEqual(result["unresolved_owner_decisions"], [])

if __name__ == "__main__":
    unittest.main()
