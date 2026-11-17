import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from issue_roadmap_sync import (
    RoadmapReconciliationError,
    build_reconciliation_proposal,
    validate_task_graph,
)


SHA_A = "a" * 40
SHA_B = "b" * 40
NOW = "2026-11-16T12:00:00Z"


def task(key="issue-10", number=10, status="approved", **overrides):
    value = {
        "task_key": key,
        "issue_number": number,
        "status": status,
        "dependencies": [],
        "source_updated_at": NOW,
    }
    value.update(overrides)
    return value


def issue(number=10, state="closed", **overrides):
    value = {"number": number, "state": state, "updated_at": NOW}
    value.update(overrides)
    return value


def pr(number=110, issue_number=10, state="closed", merged=True, **overrides):
    value = {
        "number": number,
        "issue_number": issue_number,
        "state": state,
        "merged": merged,
        "head_sha": SHA_A,
        "merge_commit_sha": SHA_B if merged else None,
        "link_evidence": "github-cross-reference-event",
    }
    value.update(overrides)
    return value


def checks(sha=SHA_A):
    return [
        {
            "id": 1001,
            "name": "audit",
            "head_sha": sha,
            "conclusion": "success",
            "html_url": "https://github.com/CarAutopsy/carautopsy/runs/1001",
        },
        {
            "id": 1002,
            "name": "validate",
            "head_sha": sha,
            "conclusion": "success",
            "html_url": "https://github.com/CarAutopsy/carautopsy/runs/1002",
        },
    ]


class RoadmapSyncTests(unittest.TestCase):
    def test_exact_head_success_and_closed_issue_propose_done_only_after_owner_approval(self):
        report = build_reconciliation_proposal(
            [task()], [issue()], [pr()], checks()
        )
        self.assertEqual(report["proposals"], [])
        self.assertEqual(report["unchanged"][0]["proposed_status"], "done")
        self.assertTrue(report["unchanged"][0]["requires_owner_approval"])
        self.assertFalse(report["roadmap_modified"])
        self.assertFalse(report["github_modified"])

        approved = build_reconciliation_proposal(
            [task()], [issue()], [pr()], checks(),
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(approved["proposals"][0]["to_status"], "done")
        self.assertEqual(approved["proposals"][0]["evidence"]["head_sha"], SHA_A)
        self.assertEqual(approved["proposals"][0]["evidence"]["merge_commit_sha"], SHA_B)
        self.assertEqual(
            [item["name"] for item in approved["proposals"][0]["evidence"]["check_evidence"]],
            ["audit", "validate"],
        )
        self.assertFalse(approved["proposals"][0]["requires_owner_approval"])

    def test_check_runs_for_different_sha_do_not_complete_task(self):
        report = build_reconciliation_proposal(
            [task()], [issue()], [pr()], checks(SHA_B),
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"], [])
        self.assertIn("exact-head", report["unchanged"][0]["reason"])

    def test_missing_required_check_blocks_completion(self):
        report = build_reconciliation_proposal(
            [task()], [issue()], [pr()], checks()[:1],
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"], [])
        self.assertEqual(report["unchanged"][0]["evidence"]["missing_checks"], ["validate"])

    def test_closed_issue_without_merged_pr_never_becomes_done(self):
        report = build_reconciliation_proposal(
            [task()], [issue()], [], [],
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"], [])
        self.assertIn("insufficient", report["unchanged"][0]["reason"])

    def test_open_issue_with_verified_open_pr_proposes_in_progress(self):
        report = build_reconciliation_proposal(
            [task(status="approved")], [issue(state="open")],
            [pr(state="open", merged=False)], [],
        )
        self.assertEqual(report["unchanged"][0]["proposed_status"], "in_progress")
        self.assertTrue(report["unchanged"][0]["requires_owner_approval"])

    def test_unverified_pr_issue_association_is_ignored(self):
        report = build_reconciliation_proposal(
            [task()], [issue()], [pr(link_evidence="pr-body-text")], checks(),
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"], [])
        self.assertIn("insufficient", report["unchanged"][0]["reason"])

    def test_newer_issue_snapshot_is_marked_stale_and_not_reconciled(self):
        older = "2026-11-15T12:00:00Z"
        report = build_reconciliation_proposal(
            [task(source_updated_at=older)], [issue()], [pr()], checks(),
            approved_task_keys={"issue-10"},
        )
        self.assertTrue(report["unchanged"][0]["stale"])
        self.assertIn("stale", report["unchanged"][0]["reason"])
        self.assertEqual(report["proposals"], [])

    def test_missing_issue_snapshot_is_visible_and_stale(self):
        report = build_reconciliation_proposal([task()], [], [], [])
        self.assertTrue(report["unchanged"][0]["stale"])
        self.assertIn("missing", report["unchanged"][0]["reason"])

    def test_dependencies_must_be_done_before_status_change(self):
        tasks = [
            task("issue-9", 9, status="approved"),
            task("issue-10", 10, status="approved", dependencies=["issue-9"]),
        ]
        report = build_reconciliation_proposal(
            tasks, [issue(9), issue(10)], [pr()], checks(),
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"], [])
        blocked = next(item for item in report["unchanged"] if item["task_key"] == "issue-10")
        self.assertEqual(blocked["blocked_by"], ["issue-9"])

    def test_unknown_dependency_and_cycle_are_rejected(self):
        with self.assertRaisesRegex(RoadmapReconciliationError, "unknown dependency"):
            validate_task_graph([task(dependencies=["missing-task"])])
        with self.assertRaisesRegex(RoadmapReconciliationError, "dependency cycle"):
            validate_task_graph([
                task("task-one", 1, dependencies=["task-two"]),
                task("task-two", 2, dependencies=["task-one"]),
            ])

    def test_duplicate_task_and_issue_ids_are_rejected(self):
        with self.assertRaisesRegex(RoadmapReconciliationError, "duplicate task_key"):
            validate_task_graph([task(), task()])
        with self.assertRaisesRegex(RoadmapReconciliationError, "duplicate issue_number"):
            validate_task_graph([task("task-one", 10), task("task-two", 10)])

    def test_malformed_linked_pr_is_rejected(self):
        with self.assertRaisesRegex(RoadmapReconciliationError, "linked PR metadata is malformed"):
            build_reconciliation_proposal(
                [task()], [issue()], [pr(head_sha="not-a-sha")], []
            )

    def test_non_boolean_merged_marker_is_rejected(self):
        with self.assertRaisesRegex(RoadmapReconciliationError, "merged marker"):
            build_reconciliation_proposal(
                [task()], [issue()], [pr(merged=1)], checks()
            )


    def test_duplicate_required_check_runs_are_ambiguous_and_block_completion(self):
        duplicate_checks = checks() + [checks()[0]]
        report = build_reconciliation_proposal(
            [task()], [issue()], [pr()], duplicate_checks,
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"], [])
        self.assertEqual(report["unchanged"][0]["evidence"]["missing_checks"], ["audit"])

    def test_check_link_repository_matching_is_case_insensitive(self):
        payload = {
            "roadmap_tasks": [task()],
            "issue_snapshots": [issue(state="closed")],
            "pull_request_evidence": [pr(merged=True)],
            "check_runs": [
                {**checks()[0], "html_url": "https://github.com/carautopsy/carautopsy/runs/1001"},
                {**checks()[1], "html_url": "https://github.com/CARAUTOPSY/CARAUTOPSY/runs/1002"},
            ],
        }
        report = build_reconciliation_proposal(
            payload["roadmap_tasks"], payload["issue_snapshots"],
            payload["pull_request_evidence"], payload["check_runs"],
            approved_task_keys={"issue-10"}, repository="CarAutopsy/carautopsy",
        )
        self.assertTrue(report["proposals"][0]["evidence"]["checks_passed"])

    def test_check_links_must_match_repository_run_id_and_unique_identity(self):
        bad_cases = (
            [
                {**checks()[0], "html_url": "https://github.com/other/repo/runs/1001"},
                checks()[1],
            ],
            [
                {**checks()[0], "html_url": "https://github.com/CarAutopsy/carautopsy/runs/9999"},
                checks()[1],
            ],
            [
                {**checks()[0], "html_url": "https://github.com/CarAutopsy/carautopsy/runs/1001)[Click](https://evil.example/"},
                checks()[1],
            ],
        )
        for invalid_checks in bad_cases:
            report = build_reconciliation_proposal(
                [task()], [issue()], [pr()], invalid_checks,
                approved_task_keys={"issue-10"},
            )
            self.assertEqual(report["proposals"], [])
            self.assertFalse(report["unchanged"][0]["evidence"]["checks_passed"])

        duplicate_identity = checks()
        duplicate_identity[1]["id"] = duplicate_identity[0]["id"]
        duplicate_identity[1]["html_url"] = duplicate_identity[0]["html_url"]
        report = build_reconciliation_proposal(
            [task()], [issue()], [pr()], duplicate_identity,
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"], [])
        self.assertEqual(report["unchanged"][0]["evidence"]["missing_checks"], ["audit", "validate"])
    def test_boolean_issue_reference_cannot_match_issue_one(self):
        with self.assertRaisesRegex(RoadmapReconciliationError, "invalid issue_number or PR number"):
            build_reconciliation_proposal(
                [task("task-one", 1)],
                [issue(1)],
                [pr(issue_number=True)],
                checks(),
            )


    def test_reopened_issue_with_merged_pr_routes_to_owner_triage_not_done(self):
        reopened_at = "2026-11-17T12:00:00Z"
        report = build_reconciliation_proposal(
            [task(status="in_progress", source_updated_at=reopened_at)],
            [issue(state="open", updated_at=reopened_at)],
            [pr()],
            checks(),
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"][0]["to_status"], "needs-owner-triage")
        self.assertNotEqual(report["proposals"][0]["to_status"], "done")

    def test_open_issue_with_merged_pr_routes_to_triage_even_without_ci(self):
        report = build_reconciliation_proposal(
            [task(status="in_progress")],
            [issue(state="open")],
            [pr()],
            [],
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"][0]["to_status"], "needs-owner-triage")
        self.assertFalse(report["proposals"][0]["evidence"]["checks_passed"])
        self.assertEqual(
            report["proposals"][0]["evidence"]["missing_checks"], ["audit", "validate"]
        )


    def test_duplicate_ci_runs_do_not_hide_open_issue_merge_triage(self):
        duplicate_checks = checks() + [checks()[0]]
        report = build_reconciliation_proposal(
            [task(status="in_progress")],
            [issue(state="open")],
            [pr()],
            duplicate_checks,
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"][0]["to_status"], "needs-owner-triage")
        self.assertFalse(report["proposals"][0]["evidence"]["checks_passed"])
        self.assertEqual(
            report["proposals"][0]["evidence"]["missing_checks"], ["audit"]
        )

    def test_closed_issue_with_open_pr_routes_to_owner_triage(self):
        report = build_reconciliation_proposal(
            [task(status="approved")],
            [issue(state="closed")],
            [pr(state="open", merged=False)],
            [],
            approved_task_keys={"issue-10"},
        )
        self.assertEqual(report["proposals"][0]["to_status"], "needs-owner-triage")

    def test_protected_roadmap_states_survive_without_owner_approval(self):
        tasks = [
            task("issue-10", 10, status="blocked", protected_hive_gates={
                "HIVE_RESEARCH_PAUSED": True,
                "VERIFIED_RETRIEVAL_AVAILABLE": False,
                "approved_source_manifest": [],
            }),
            task("issue-11", 11, status="needs-owner-triage"),
        ]
        before = copy.deepcopy(tasks)
        report = build_reconciliation_proposal(
            tasks,
            [issue(10), issue(11)],
            [pr(110, 10), pr(111, 11)],
            checks(),
        )
        self.assertEqual(report["proposals"], [])
        unchanged = {item["task_key"]: item for item in report["unchanged"]}
        self.assertEqual(unchanged["issue-10"]["status"], "blocked")
        self.assertEqual(unchanged["issue-11"]["status"], "needs-owner-triage")
        self.assertTrue(unchanged["issue-10"]["requires_owner_approval"])
        self.assertEqual(tasks, before)
        self.assertEqual(
            tasks[0]["protected_hive_gates"],
            {"HIVE_RESEARCH_PAUSED": True, "VERIFIED_RETRIEVAL_AVAILABLE": False, "approved_source_manifest": []},
        )

    def test_ambiguous_pr_links_do_not_suppress_independent_tasks(self):
        report = build_reconciliation_proposal(
            [task("issue-10", 10), task("issue-11", 11)],
            [issue(10), issue(11)],
            [pr(110, 10), pr(111, 10), pr(112, 11)],
            checks(),
            approved_task_keys={"issue-11"},
        )
        self.assertEqual([item["task_key"] for item in report["proposals"]], ["issue-11"])
        ambiguous = next(item for item in report["unchanged"] if item["task_key"] == "issue-10")
        self.assertIn("ambiguous or conflicting linked PR", ambiguous["reason"])


    def test_conflicting_records_for_same_pr_number_are_isolated(self):
        report = build_reconciliation_proposal(
            [task("issue-10", 10), task("issue-11", 11), task("issue-12", 12)],
            [issue(10), issue(11), issue(12)],
            [
                pr(110, 10),
                pr(110, 11, state="open", merged=False, merge_commit_sha=None),
                pr(112, 12),
            ],
            checks(),
            approved_task_keys={"issue-10", "issue-11", "issue-12"},
        )
        self.assertEqual([item["task_key"] for item in report["proposals"]], ["issue-12"])
        for key in ("issue-10", "issue-11"):
            item = next(row for row in report["unchanged"] if row["task_key"] == key)
            self.assertIn("conflicting linked PR", item["reason"])

    def test_same_pr_can_reference_multiple_issues_when_metadata_matches(self):
        report = build_reconciliation_proposal(
            [task("issue-10", 10), task("issue-11", 11)],
            [issue(10), issue(11)],
            [pr(110, 10), pr(110, 11)],
            checks(),
            approved_task_keys={"issue-10", "issue-11"},
        )
        self.assertEqual(
            [item["task_key"] for item in report["proposals"]],
            ["issue-10", "issue-11"],
        )

    def test_duplicate_issue_snapshots_do_not_suppress_independent_tasks(self):
        report = build_reconciliation_proposal(
            [task("issue-10", 10), task("issue-11", 11)],
            [issue(10), issue(10), issue(11)],
            [pr(110, 10), pr(111, 11)],
            checks(),
            approved_task_keys={"issue-11"},
        )
        self.assertEqual([item["task_key"] for item in report["proposals"]], ["issue-11"])
        ambiguous = next(item for item in report["unchanged"] if item["task_key"] == "issue-10")
        self.assertIn("duplicate issue snapshots", ambiguous["reason"])

    def test_direct_caller_cannot_weaken_mandatory_checks(self):
        report = build_reconciliation_proposal(
            [task()], [issue()], [pr()], checks()[:1],
            approved_task_keys={"issue-10"},
            required_checks=("audit",),
        )
        self.assertEqual(report["proposals"], [])
        self.assertEqual(report["unchanged"][0]["evidence"]["missing_checks"], ["validate"])

    def test_inputs_are_not_mutated_and_output_is_deterministic(self):
        tasks = [task()]
        issues = [issue()]
        prs = [pr()]
        run_checks = checks()
        before = copy.deepcopy((tasks, issues, prs, run_checks))
        first = build_reconciliation_proposal(tasks, issues, prs, run_checks)
        second = build_reconciliation_proposal(tasks, issues, prs, run_checks)
        self.assertEqual(first, second)
        self.assertEqual((tasks, issues, prs, run_checks), before)


    def test_future_roadmap_timestamp_is_stale_not_a_freshness_bypass(self):
        future = "2026-11-17T12:00:00Z"
        report = build_reconciliation_proposal(
            [task(source_updated_at=future)], [issue()], [pr()], checks(),
            approved_task_keys={"issue-10"},
        )
        self.assertTrue(report["unchanged"][0]["stale"])
        self.assertEqual(report["proposals"], [])

    def test_long_dependency_chain_does_not_recurse(self):
        tasks = []
        for index in range(1200):
            key = f"task-{index:04d}"
            dependencies = [] if index == 0 else [f"task-{index - 1:04d}"]
            tasks.append(task(key, index + 1, dependencies=dependencies))
        self.assertEqual(len(validate_task_graph(tasks)), 1200)

    def test_invalid_timestamps_and_approval_inputs_fail_closed(self):
        with self.assertRaisesRegex(RoadmapReconciliationError, "timezone"):
            validate_task_graph([task(source_updated_at="2026-11-16T12:00:00")])
        with self.assertRaisesRegex(RoadmapReconciliationError, "approved_task_keys"):
            build_reconciliation_proposal(
                [task()], [issue()], [pr()], checks(), approved_task_keys={"unknown"}
            )

    def test_required_check_names_must_match_renderer_safe_character_set(self):
        for invalid_name in ("unit (linux)", "audit\\n\\n## Approved", "x" * 101):
            with self.subTest(name=invalid_name):
                with self.assertRaises(RoadmapReconciliationError):
                    build_reconciliation_proposal(
                        [task()], [issue()], [pr()], checks(),
                        required_checks=(invalid_name,),
                    )


if __name__ == "__main__":
    unittest.main()
