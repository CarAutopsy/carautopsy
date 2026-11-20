"""Static workflow-contract tests for the autonomous pipeline.

These tests pin the job graph, least-privilege permission split, research-pause
guards and read-only artifact boundaries of ``autonomous-pipeline.yml``. They
follow the CivLab reuse assessment's workflow-contract follow-up (issue #114)
and add coverage only: no workflow, policy or activation behavior is changed.
"""
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "autonomous-pipeline.yml"


def load_workflow():
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


class AutonomousPipelineWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = load_workflow()
        cls.source = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.run_job = cls.workflow["jobs"]["run"]
        cls.crawler = cls.workflow["jobs"]["issue-roadmap-crawler"]

    def _step(self, name, job=None):
        return next(step for step in (job or self.run_job)["steps"] if step.get("name") == name)

    def test_least_privilege_default_and_job_permission_split(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(self.run_job["permissions"], {"contents": "write", "pull-requests": "write"})
        self.assertEqual(self.crawler["permissions"], {
            "contents": "read",
            "issues": "read",
            "pull-requests": "read",
            "checks": "read",
        })

    def test_job_graph_separates_crawler_only_from_write_job(self):
        self.assertIn("inputs.run_mode != 'crawler-only'", self.run_job["if"])
        self.assertEqual(
            self.crawler["if"],
            "github.event_name == 'schedule' || (github.event_name == 'workflow_dispatch' "
            "&& inputs.run_mode == 'crawler-only')",
        )
        self.assertEqual(self.run_job["concurrency"]["group"], "autonomous-pipeline-research")
        self.assertEqual(self.run_job["concurrency"]["cancel-in-progress"], "false")
        self.assertIn("autonomous-pipeline-issue-crawler-", self.crawler["concurrency"]["group"])

    def test_paid_and_manual_routes_are_manual_dispatch_only(self):
        smoke = self._step("Provider smoke test only")
        self.assertIn("github.event_name == 'workflow_dispatch'", smoke["if"])
        self.assertIn("inputs.run_mode == 'provider-smoke-test'", smoke["if"])
        tco = self._step("Gated TCO pipeline")
        self.assertIn("github.event_name == 'workflow_dispatch'", tco["if"])
        self.assertIn("inputs.run_mode == 'full'", tco["if"])
        self.assertEqual(tco["run"], "python scripts/autonomous_pipeline.py")

    def test_research_preflight_guards_token_and_provider_steps(self):
        preflight = self._step("Preflight - research pause")
        self.assertEqual(preflight["id"], "preflight")
        self.assertIn("VERIFIED_RETRIEVAL_AVAILABLE = False", preflight["run"])
        for name in ("Require PR automation token", "Hive research + two independent AI audits"):
            step = self._step(name)
            self.assertIn("steps.preflight.outputs.paused != 'true'", step["if"])
            self.assertIn("inputs.run_mode == 'research-only'", step["if"])
        self.assertIn("steps.preflight.outputs.paused != 'true'", self._step("Install deps")["if"])

    def test_crawler_uploads_only_the_two_read_only_artifacts(self):
        uploads = [
            step for step in self.crawler["steps"]
            if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        self.assertEqual(
            [step["with"]["name"] for step in uploads],
            ["issue-roadmap-dry-run", "issue-roadmap-reconciliation-proposal"],
        )
        for step in uploads:
            self.assertEqual(step["with"]["if-no-files-found"], "error")
            self.assertEqual(step["with"]["retention-days"], "7")
            self.assertTrue(step["with"]["path"].startswith("${{ runner.temp }}/"))

    def test_crawler_job_has_no_write_credentials_or_mutation_commands(self):
        crawler_source = self.source.split("  issue-roadmap-crawler:", 1)[1]
        self.assertNotIn("secrets.", crawler_source)
        self.assertNotIn("persist-credentials: true", crawler_source)
        self.assertNotIn("git push", crawler_source)
        self.assertNotIn("gh issue", crawler_source)
        self.assertNotIn("gh pr", crawler_source)
        self.assertIn("persist-credentials: false", crawler_source)
        self.assertIn("--fetch-github --state all", crawler_source)
        self.assertIn("--render-artifact-json", crawler_source)


if __name__ == "__main__":
    unittest.main()
