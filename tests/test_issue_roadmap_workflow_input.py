import sys
import unittest

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from issue_roadmap_workflow_input import WorkflowInputError, build_evidence_input


REPOSITORY = "CarAutopsy/carautopsy"
STAMP = "2026-11-17T12:00:00Z"


def crawler(issues=None):
    return {
        "schema_version": 1,
        "mode": "dry-run",
        "source": "github-all-issues",
        "repository": REPOSITORY,
        "roadmap_modified": False,
        "github_modified": False,
        "task_dispatch_performed": False,
        "issue_snapshots": issues or [],
    }


def roadmap(tasks=None):
    return {"schema_version": 1, "repository": REPOSITORY, "tasks": tasks or []}


def task(number=10):
    return {
        "task_key": f"issue-{number}",
        "issue_number": number,
        "status": "approved",
        "dependencies": [],
        "source_updated_at": STAMP,
    }


class RoadmapWorkflowInputTests(unittest.TestCase):
    def test_selects_only_explicitly_mapped_issues_and_projects_allowlist(self):
        result = build_evidence_input(
            crawler([
                {"number": 11, "state": "open", "updated_at": STAMP},
                {"number": 10, "state": "closed", "updated_at": STAMP},
            ]),
            roadmap([task()]),
            repository=REPOSITORY,
        )
        self.assertEqual(result["roadmap_tasks"], [task()])
        self.assertEqual(result["issue_snapshots"], [
            {"number": 10, "state": "closed", "updated_at": STAMP}
        ])
        self.assertNotIn("body", result["issue_snapshots"][0])

    def test_empty_canonical_snapshot_produces_empty_evidence_scope(self):
        result = build_evidence_input(
            crawler([{"number": 10, "state": "open", "updated_at": STAMP}]),
            roadmap(),
            repository=REPOSITORY,
        )
        self.assertEqual(result["roadmap_tasks"], [])
        self.assertEqual(result["issue_snapshots"], [])

    def test_repository_identity_is_case_insensitive(self):
        lower = "carautopsy/carautopsy"
        crawler_report = crawler()
        crawler_report["repository"] = lower
        roadmap_state = roadmap()
        roadmap_state["repository"] = REPOSITORY.swapcase()
        result = build_evidence_input(crawler_report, roadmap_state, repository=REPOSITORY)
        self.assertEqual(result["repository"], REPOSITORY)

    def test_rejects_more_than_collector_issue_limit(self):
        tasks = [task(number) for number in range(1, 502)]
        with self.assertRaisesRegex(WorkflowInputError, "collector limit"):
            build_evidence_input(crawler(), roadmap(tasks), repository=REPOSITORY)

    def test_rejects_filtered_or_fixture_crawler_sources(self):
        for source in ("github-open-issues", "github-closed-issues", "fixture"):
            with self.subTest(source=source):
                report = crawler()
                report["source"] = source
                with self.assertRaisesRegex(WorkflowInputError, "all-state snapshot"):
                    build_evidence_input(report, roadmap(), repository=REPOSITORY)

    def test_rejects_repository_mismatch(self):
        with self.assertRaisesRegex(WorkflowInputError, "identity or schema"):
            build_evidence_input(crawler(), {
                "schema_version": 1, "repository": "other/repo", "tasks": []
            }, repository=REPOSITORY)

    def test_rejects_missing_task_timestamp(self):
        invalid = task()
        invalid["source_updated_at"] = None
        with self.assertRaisesRegex(WorkflowInputError, "timezone-aware"):
            build_evidence_input(crawler(), roadmap([invalid]), repository=REPOSITORY)

    def test_rejects_duplicate_mapped_issue_snapshots(self):
        with self.assertRaisesRegex(WorkflowInputError, "duplicate mapped"):
            build_evidence_input(
                crawler([
                    {"number": 10, "state": "open", "updated_at": STAMP},
                    {"number": 10, "state": "open", "updated_at": STAMP},
                ]),
                roadmap([task()]),
                repository=REPOSITORY,
            )

    def test_rejects_crawler_report_with_write_flags(self):
        report = crawler()
        report["github_modified"] = True
        with self.assertRaisesRegex(WorkflowInputError, "read-only"):
            build_evidence_input(report, roadmap(), repository=REPOSITORY)


if __name__ == "__main__":
    unittest.main()
