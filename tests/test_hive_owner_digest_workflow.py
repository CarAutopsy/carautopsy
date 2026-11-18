"""Static security contracts for the read-only Hive owner digest workflow."""
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_workflow(name):
    path = ROOT / ".github" / "workflows" / name
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


class HiveOwnerDigestWorkflowTests(unittest.TestCase):
    def test_digest_workflow_is_scheduled_manual_and_read_only(self):
        workflow = load_workflow("hive-owner-digest.yml")
        self.assertEqual(workflow["on"]["schedule"], [{"cron": "12,27,42,57 * * * *"}])
        self.assertIn("workflow_dispatch", workflow["on"])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["digest"]
        self.assertEqual(job["permissions"], {"contents": "read"})
        self.assertEqual(job["timeout-minutes"], "5")

        source = (ROOT / ".github" / "workflows" / "hive-owner-digest.yml").read_text(encoding="utf-8")
        self.assertNotIn("secrets.", source)
        self.assertNotIn("contents: write", source)
        self.assertNotIn("pull-requests: write", source)
        self.assertNotIn("git push", source)
        self.assertIn("hive_owner_digest_snapshot.py", source)
        snapshot_helper = (ROOT / "scripts" / "hive_owner_digest_snapshot.py").read_text(encoding="utf-8")
        self.assertIn("Hive-Ledger-SHA256", snapshot_helper)
        self.assertIn("interpret-trailers", snapshot_helper)
        self.assertIn("hive-state-branch-absent", snapshot_helper)
        self.assertIn("persist-credentials: false", source)
        self.assertIn("retention-days: 14", source)

    def test_digest_workflow_does_not_expand_existing_research_or_tco_permissions(self):
        workflow = load_workflow("autonomous-pipeline.yml")
        crawler = workflow["jobs"]["issue-roadmap-crawler"]
        self.assertEqual(
            crawler["permissions"],
            {
                "contents": "read",
                "issues": "read",
                "pull-requests": "read",
                "checks": "read",
            },
        )
        run_job = workflow["jobs"]["run"]
        tco = next(step for step in run_job["steps"] if step.get("name") == "Gated TCO pipeline")
        research = next(step for step in run_job["steps"] if step.get("name") == "Hive research + two independent AI audits")
        self.assertIn("run_mode == 'full'", tco["if"])
        self.assertIn("run_mode == 'research-only'", research["if"])
        self.assertTrue(any(step.get("name") == "Preflight - research pause" for step in run_job["steps"]))

    def test_owner_digest_workflow_uses_separate_concurrency_and_artifact(self):
        workflow = load_workflow("hive-owner-digest.yml")
        self.assertEqual(workflow["concurrency"]["group"], "hive-owner-digest")
        self.assertEqual(workflow["concurrency"]["cancel-in-progress"], "false")
        steps = workflow["jobs"]["digest"]["steps"]
        self.assertTrue(any(step.get("name") == "Prepare and verify Hive snapshot" for step in steps))
        upload = next(step for step in steps if step.get("name") == "Upload sanitized digest artifact")
        self.assertEqual(upload["uses"], "actions/upload-artifact@v6")
        self.assertEqual(upload["with"]["name"], "hive-owner-digest")


if __name__ == "__main__":
    unittest.main()
