import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from issue_roadmap_evidence import EvidenceCollectionError, collect_github_evidence
from issue_roadmap_sync import RoadmapReconciliationError, build_reconciliation_proposal

SHA = "a" * 40
MERGE_SHA = "b" * 40


def response(payload, links=None):
    item = Mock()
    item.json.return_value = payload
    item.links = links or {}
    item.raise_for_status.return_value = None
    return item


class EvidenceCollectorTests(unittest.TestCase):
    def test_collects_only_timeline_cross_referenced_pr_and_exact_head_checks(self):
        timeline = [
            {"event": "cross-referenced", "source": {"issue": {"number": 22, "repository": {"full_name": "CarAutopsy/carautopsy"}, "pull_request": {"url": "ignored"}}},
             "body": "untrusted comment must not be retained"},
            {"event": "commented", "source": {"issue": {"number": 23, "pull_request": {"url": "ignored"}}}},
            {"event": "cross-referenced", "source": {"issue": {"number": 24}}},
        ]
        pr = {"number": 22, "state": "closed", "merged": True, "head": {"sha": SHA},
              "merge_commit_sha": MERGE_SHA, "body": "untrusted PR body"}
        checks = {"total_count": 2, "check_runs": [
            {"id": 101, "name": "audit", "head_sha": SHA, "conclusion": "success",
             "html_url": "https://github.com/CarAutopsy/carautopsy/runs/101"},
            {"id": 102, "name": "validate", "head_sha": SHA, "conclusion": "success",
             "html_url": "https://github.com/CarAutopsy/carautopsy/runs/102"},
        ]}
        session = Mock()
        session.get.side_effect = [response(timeline), response(pr), response(checks)]
        result = collect_github_evidence(
            "CarAutopsy/carautopsy",
            [{"number": 10, "state": "closed", "updated_at": "2026-11-17T10:00:00Z"}],
            token="secret", session=session,
        )
        self.assertEqual(len(result["pull_request_evidence"]), 1)
        evidence = result["pull_request_evidence"][0]
        self.assertEqual(evidence["issue_number"], 10)
        self.assertEqual(evidence["number"], 22)
        self.assertEqual(evidence["link_evidence"], "github-cross-reference-event")
        self.assertEqual(evidence["head_sha"], SHA)
        self.assertNotIn("body", evidence)
        self.assertEqual([item["name"] for item in result["check_runs"]], ["audit", "validate"])
        self.assertTrue(all(item["head_sha"] == SHA for item in result["check_runs"]))
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual(session.get.call_args_list[0].kwargs["headers"]["Authorization"], "Bearer secret")

    def test_multiple_issues_referencing_same_pr_fetch_pr_and_checks_once(self):
        timeline = response([{"event": "cross-referenced", "source": {"issue": {"number": 22, "repository": {"full_name": "owner/repo"}, "pull_request": {}}}}])
        pr = response({"number": 22, "state": "open", "merged": False, "head": {"sha": SHA}, "merge_commit_sha": None})
        checks = response({"check_runs": []})
        session = Mock()
        session.get.side_effect = [timeline, timeline, pr, checks]
        result = collect_github_evidence("owner/repo", [
            {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"},
            {"number": 11, "state": "open", "updated_at": "2026-11-17T10:00:00Z"},
        ], session=session)
        self.assertEqual(len(result["pull_request_evidence"]), 2)
        self.assertEqual(session.get.call_count, 4)
        self.assertEqual(result["check_runs"], [])


    def test_ignores_cross_repository_references_with_and_without_local_number_collisions(self):
        foreign = response([
            {"event": "cross-referenced", "source": {"issue": {"number": 22,
             "repository": {"full_name": "elsewhere/project"}, "pull_request": {}}}},
            {"event": "cross-referenced", "source": {"issue": {"number": 999,
             "repository": {"full_name": "elsewhere/project"}, "pull_request": {}}}},
        ])
        session = Mock()
        session.get.return_value = foreign
        result = collect_github_evidence("owner/repo", [
            {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"}
        ], session=session)
        self.assertEqual(result, {"pull_request_evidence": [], "check_runs": []})
        # No same-number local PR lookup is allowed for either foreign reference.
        self.assertEqual(session.get.call_count, 1)

    def test_rejects_cross_reference_without_structured_repository_identity(self):
        timeline = response([{"event": "cross-referenced", "source": {"issue": {
            "number": 22, "pull_request": {}}}}])
        session = Mock()
        session.get.return_value = timeline
        with self.assertRaisesRegex(EvidenceCollectionError, "source repository identity"):
            collect_github_evidence("owner/repo", [
                {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"}
            ], session=session)

    def test_fetches_check_runs_once_for_distinct_shared_head_sha(self):
        timeline = response([
            {"event": "cross-referenced", "source": {"issue": {"number": number,
             "repository": {"full_name": "owner/repo"}, "pull_request": {}}}}
            for number in (22, 23)
        ])
        pr22 = response({"number": 22, "state": "open", "merged": False,
                         "head": {"sha": SHA}, "merge_commit_sha": None})
        pr23 = response({"number": 23, "state": "open", "merged": False,
                         "head": {"sha": SHA}, "merge_commit_sha": None})
        checks = response({"check_runs": [{"id": 101, "name": "audit", "head_sha": SHA,
                                           "conclusion": "success", "html_url": "https://github.com/owner/repo/runs/101"}]})
        session = Mock()
        session.get.side_effect = [timeline, pr22, pr23, checks]
        result = collect_github_evidence("owner/repo", [
            {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"}
        ], session=session)
        self.assertEqual(len(result["pull_request_evidence"]), 2)
        self.assertEqual(len(result["check_runs"]), 1)
        self.assertEqual(session.get.call_count, 4)
        self.assertEqual(sum("/check-runs" in call.args[0] for call in session.get.call_args_list), 1)

    def test_rejects_check_run_sha_that_differs_from_requested_pr_head(self):
        timeline = response([{"event": "cross-referenced", "source": {"issue": {"number": 22, "repository": {"full_name": "owner/repo"}, "pull_request": {}}}}])
        pr = response({"number": 22, "state": "open", "merged": False, "head": {"sha": SHA}, "merge_commit_sha": None})
        checks = response({"check_runs": [{"id": 101, "name": "audit", "head_sha": MERGE_SHA,
                                           "conclusion": "success", "html_url": "https://github.com/owner/repo/runs/101"}]})
        session = Mock()
        session.get.side_effect = [timeline, pr, checks]
        with self.assertRaisesRegex(EvidenceCollectionError, "head SHA does not match"):
            collect_github_evidence("owner/repo", [
                {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"}
            ], session=session)


    def test_collector_output_enters_deterministic_owner_gated_reconciliation(self):
        tasks = [{
            "task_key": "issue-10", "issue_number": 10, "status": "approved",
            "dependencies": [], "source_updated_at": "2026-11-17T10:00:00Z",
            "protected_hive_gates": {"HIVE_RESEARCH_PAUSED": True,
                                     "VERIFIED_RETRIEVAL_AVAILABLE": False,
                                     "approved_source_manifest": []},
        }]
        issues = [{"number": 10, "state": "closed", "updated_at": "2026-11-17T10:00:00Z"}]
        prs = [{"number": 22, "issue_number": 10, "state": "closed", "merged": True,
                "head_sha": SHA, "merge_commit_sha": MERGE_SHA,
                "link_evidence": "github-cross-reference-event"}]
        checks = [
            {"id": 101, "name": "audit", "head_sha": SHA, "conclusion": "success",
             "html_url": "https://github.com/CarAutopsy/carautopsy/runs/101"},
            {"id": 102, "name": "validate", "head_sha": SHA, "conclusion": "success",
             "html_url": "https://github.com/CarAutopsy/carautopsy/runs/102"},
        ]
        before = __import__("copy").deepcopy(tasks)
        first = build_reconciliation_proposal(tasks, issues, prs, checks)
        second = build_reconciliation_proposal(tasks, issues, prs, checks)
        self.assertEqual(first, second)
        self.assertEqual(first["proposals"], [])
        self.assertEqual(first["unchanged"][0]["proposed_status"], "done")
        self.assertTrue(first["unchanged"][0]["requires_owner_approval"])
        self.assertEqual(tasks, before)
        self.assertEqual(tasks[0]["protected_hive_gates"], {
            "HIVE_RESEARCH_PAUSED": True, "VERIFIED_RETRIEVAL_AVAILABLE": False,
            "approved_source_manifest": [],
        })


    def test_reopened_issue_routes_to_owner_triage_not_done(self):
        reopened_at = "2026-11-17T12:00:00Z"
        task = {"task_key": "issue-10", "issue_number": 10, "status": "in_progress",
                "dependencies": [], "source_updated_at": reopened_at}
        issue = {"number": 10, "state": "open", "updated_at": reopened_at}
        pr = {"number": 22, "issue_number": 10, "state": "closed", "merged": True,
              "head_sha": SHA, "merge_commit_sha": MERGE_SHA,
              "link_evidence": "github-cross-reference-event"}
        check_runs = [
            {"id": 101, "name": "audit", "head_sha": SHA, "conclusion": "success",
             "html_url": "https://github.com/CarAutopsy/carautopsy/runs/101"},
            {"id": 102, "name": "validate", "head_sha": SHA, "conclusion": "success",
             "html_url": "https://github.com/CarAutopsy/carautopsy/runs/102"},
        ]
        report = build_reconciliation_proposal([task], [issue], [pr], check_runs,
                                               approved_task_keys={"issue-10"})
        self.assertEqual(report["proposals"][0]["to_status"], "needs-owner-triage")
        self.assertNotEqual(report["proposals"][0]["to_status"], "done")

    def test_reconciliation_rejects_duplicate_task_ids_and_dependency_cycles(self):
        task = {"task_key": "task-one", "issue_number": 10, "status": "approved",
                "dependencies": [], "source_updated_at": "2026-11-17T10:00:00Z"}
        with self.assertRaisesRegex(RoadmapReconciliationError, "duplicate task_key"):
            build_reconciliation_proposal([task, dict(task)], [], [], [])
        cyclic = [
            {**task, "task_key": "task-one", "issue_number": 10, "dependencies": ["task-two"]},
            {**task, "task_key": "task-two", "issue_number": 11, "dependencies": ["task-one"]},
        ]
        with self.assertRaisesRegex(RoadmapReconciliationError, "dependency cycle"):
            build_reconciliation_proposal(cyclic, [], [], [])

    def test_reconciliation_does_not_use_stale_or_reopened_issue_as_done(self):
        task = {"task_key": "issue-10", "issue_number": 10, "status": "in_progress",
                "dependencies": [], "source_updated_at": "2026-11-16T10:00:00Z"}
        issue = {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"}
        pr = {"number": 22, "issue_number": 10, "state": "closed", "merged": True,
              "head_sha": SHA, "merge_commit_sha": MERGE_SHA,
              "link_evidence": "github-cross-reference-event"}
        check_runs = [
            {"id": 101, "name": "audit", "head_sha": SHA, "conclusion": "success",
             "html_url": "https://github.com/CarAutopsy/carautopsy/runs/101"},
            {"id": 102, "name": "validate", "head_sha": SHA, "conclusion": "success",
             "html_url": "https://github.com/CarAutopsy/carautopsy/runs/102"},
        ]
        report = build_reconciliation_proposal([task], [issue], [pr], check_runs,
                                               approved_task_keys={"issue-10"})
        self.assertEqual(report["proposals"], [])
        self.assertTrue(report["unchanged"][0]["stale"])
        self.assertNotEqual(report["unchanged"][0].get("proposed_status"), "done")

    def test_rejects_duplicate_or_unprojected_issue_snapshots(self):
        issue = {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"}
        with self.assertRaisesRegex(EvidenceCollectionError, "duplicate"):
            collect_github_evidence("owner/repo", [issue, issue], session=Mock())
        with self.assertRaisesRegex(EvidenceCollectionError, "unsupported"):
            collect_github_evidence("owner/repo", [{**issue, "body": "must not be read"}], session=Mock())

    def test_rejects_untrusted_timeline_pagination(self):
        first = response([], {"next": {"url": "https://evil.example/repos/owner/repo/issues/10/timeline?page=2"}})
        session = Mock()
        session.get.return_value = first
        with self.assertRaisesRegex(EvidenceCollectionError, "unexpected pagination"):
            collect_github_evidence("owner/repo", [
                {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"}
            ], session=session)
        self.assertEqual(session.get.call_count, 1)

    def test_rejects_malformed_pr_head_and_merge_metadata(self):
        timeline = response([{"event": "cross-referenced", "source": {"issue": {"number": 22, "repository": {"full_name": "owner/repo"}, "pull_request": {}}}}])
        for payload in (
            {"number": 22, "state": "open", "merged": False, "head": {"sha": "bad"}},
            {"number": 22, "state": "open", "merged": 1, "head": {"sha": SHA}},
            {"number": 22, "state": "closed", "merged": True, "head": {"sha": SHA}, "merge_commit_sha": None},
        ):
            session = Mock()
            session.get.side_effect = [timeline, response(payload)]
            with self.subTest(payload=payload), self.assertRaisesRegex(EvidenceCollectionError, "metadata is malformed"):
                collect_github_evidence("owner/repo", [
                    {"number": 10, "state": "closed", "updated_at": "2026-11-17T10:00:00Z"}
                ], session=session)

    def test_api_errors_are_sanitized(self):
        import requests
        session = Mock()
        session.get.side_effect = requests.Timeout("secret-token should not leak")
        with self.assertRaises(EvidenceCollectionError) as raised:
            collect_github_evidence("owner/repo", [
                {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"}
            ], token="secret-token", session=session)
        self.assertNotIn("secret-token", str(raised.exception))
        self.assertIn("Timeout", str(raised.exception))

    def test_rejects_non_repository_and_too_many_issues_before_network(self):
        issue = {"number": 10, "state": "open", "updated_at": "2026-11-17T10:00:00Z"}
        session = Mock()
        with self.assertRaises(EvidenceCollectionError):
            collect_github_evidence("../repo", [issue], session=session)
        with self.assertRaises(EvidenceCollectionError):
            collect_github_evidence("owner/repo", [issue] * 501, session=session)
        session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
