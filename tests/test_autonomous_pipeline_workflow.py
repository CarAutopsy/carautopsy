"""Static workflow-contract tests for the autonomous pipeline.

The contract is evaluated from the parsed workflow with normalized whitespace,
not from incidental YAML formatting or raw source slicing. The helper
``contract_errors`` is also exercised against mutated copies so the tests
demonstrably detect missing jobs, missing artifacts and broken contracts.
"""
from copy import deepcopy
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "autonomous-pipeline.yml"
REQUIRED_JOBS = ("run", "issue-roadmap-crawler")
EXPECTED_ARTIFACTS = (
    "issue-roadmap-dry-run",
    "issue-roadmap-reconciliation-proposal",
)
CRAWLER_PERMISSIONS = {
    "contents": "read",
    "issues": "read",
    "pull-requests": "read",
    "checks": "read",
}
RUN_PERMISSIONS = {"contents": "write", "pull-requests": "write"}
EXPECTED_CRON = "7,22,37,52 * * * *"
EXPECTED_CRAWLER_IF = (
    "github.event_name == 'schedule' || (github.event_name == 'workflow_dispatch' "
    "&& inputs.run_mode == 'crawler-only')"
)
EXPECTED_RUN_IF = (
    "github.event_name != 'workflow_dispatch' || inputs.run_mode != 'crawler-only'"
)


class _StrictLoader(yaml.BaseLoader):
    """YAML loader that rejects duplicate mapping keys instead of last-one-wins."""

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            return super().construct_mapping(node, deep=deep)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"duplicate mapping key: {key}", key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def parse_workflow(text):
    return yaml.load(text, Loader=_StrictLoader)


def load_workflow():
    return parse_workflow(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _norm(value):
    """Collapse incidental whitespace in YAML expressions and shell commands."""
    return " ".join(str(value or "").split())


def _step(job, name):
    return next((step for step in job.get("steps", []) if step.get("name") == name), None)


def _uploads(job):
    return [
        step for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]


def contract_errors(workflow):
    """Return a list of workflow-contract violations (empty means compliant)."""
    errors = []
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return ["jobs must be a mapping"]
    for name in REQUIRED_JOBS:
        if name not in jobs:
            errors.append(f"missing job: {name}")
    if errors:
        return errors

    triggers = workflow.get("on")
    if not isinstance(triggers, dict):
        errors.append("workflow triggers are missing")
    else:
        if EXPECTED_CRON not in [
            _norm(item.get("cron")) for item in triggers.get("schedule", [])
            if isinstance(item, dict)
        ]:
            errors.append("expected heartbeat schedule trigger is missing")
        dispatch = triggers.get("workflow_dispatch")
        if not isinstance(dispatch, dict):
            errors.append("workflow_dispatch trigger is missing")
        else:
            modes = dispatch.get("inputs", {}).get("run_mode", {}).get("options", [])
            if "crawler-only" not in modes:
                errors.append("crawler-only dispatch mode is missing")

    if workflow.get("permissions") != {"contents": "read"}:
        errors.append("top-level permissions are not least privilege")
    run, crawler = jobs["run"], jobs["issue-roadmap-crawler"]
    for name, job in jobs.items():
        for value in job.get("env", {}).values():
            if "secrets." in str(value):
                errors.append(f"job-level secret exposure in: {name}")

    if run.get("permissions") != RUN_PERMISSIONS:
        errors.append("run job permissions changed")
    if crawler.get("permissions") != CRAWLER_PERMISSIONS:
        errors.append("crawler permissions are not read-only")

    if _norm(run.get("if")) != EXPECTED_RUN_IF:
        errors.append("run job crawler-only exclusion changed")
    if _norm(crawler.get("if")) != EXPECTED_CRAWLER_IF:
        errors.append("crawler trigger condition changed")

    if _norm(run.get("concurrency", {}).get("group")) != "autonomous-pipeline-research":
        errors.append("run concurrency group changed")
    if "autonomous-pipeline-issue-crawler-" not in _norm(crawler.get("concurrency", {}).get("group")):
        errors.append("crawler concurrency group changed")

    for name in (
        "Preflight - research pause",
        "Install deps",
        "Require PR automation token",
        "Hive research + two independent AI audits",
        "Provider smoke test only",
        "Gated TCO pipeline",
    ):
        if _step(run, name) is None:
            errors.append(f"missing run step: {name}")

    preflight = _step(run, "Preflight - research pause")
    if preflight is not None:
        if preflight.get("id") != "preflight":
            errors.append("preflight output id changed")
        if "VERIFIED_RETRIEVAL_AVAILABLE = False" not in _norm(preflight.get("run")):
            errors.append("preflight no longer checks the research pause flag")
    for name in ("Require PR automation token", "Hive research + two independent AI audits", "Install deps"):
        step = _step(run, name)
        if step is not None:
            condition = _norm(step.get("if"))
            if "steps.preflight.outputs.paused != 'true'" not in condition:
                errors.append(f"preflight guard lost on: {name}")
    for name in ("Provider smoke test only", "Gated TCO pipeline"):
        step = _step(run, name)
        if step is not None and "github.event_name == 'workflow_dispatch'" not in _norm(step.get("if")):
            errors.append(f"manual-dispatch guard lost on: {name}")

    tco = _step(run, "Gated TCO pipeline")
    if tco is not None:
        command = _norm(tco.get("run"))
        if not command.startswith("python scripts/autonomous_pipeline.py"):
            errors.append("full TCO route no longer calls the pipeline script")
        if "--research-only" in command:
            errors.append("full TCO route must not be a research-only invocation")

    uploads = _uploads(crawler)
    if [step.get("with", {}).get("name") for step in uploads] != list(EXPECTED_ARTIFACTS):
        errors.append("crawler artifact names changed")
    for step in uploads:
        settings = step.get("with", {})
        if settings.get("if-no-files-found") != "error":
            errors.append("upload does not fail on missing artifact")
        if settings.get("retention-days") != "7":
            errors.append("upload retention changed")
        if not _norm(settings.get("path")).startswith("${{ runner.temp }}/"):
            errors.append("upload path is not confined to runner temp")

    steps = crawler.get("steps", [])
    for step in steps:
        for value in step.get("env", {}).values():
            if "secrets." in str(value):
                errors.append("crawler job received a secret")
        command = _norm(step.get("run"))
        for mutation in ("git push", "gh issue", "gh pr "):
            if mutation in command:
                errors.append(f"crawler mutation command: {mutation}")
    checkout = next(
        (step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")),
        None,
    )
    if checkout is None or checkout.get("with", {}).get("persist-credentials") != "false":
        errors.append("crawler checkout persists credentials")
    commands = [_norm(step.get("run")) for step in steps]
    if not any("--fetch-github --state all" in command for command in commands):
        errors.append("crawler all-state fetch command missing")
    if not any("--render-artifact-json" in command for command in commands):
        errors.append("reconciliation artifact render command missing")
    return errors


class AutonomousPipelineWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = load_workflow()

    def test_workflow_satisfies_every_contract(self):
        self.assertEqual(contract_errors(self.workflow), [])

    def test_required_jobs_are_present(self):
        for name in REQUIRED_JOBS:
            with self.subTest(job=name):
                self.assertIn(name, self.workflow.get("jobs", {}))

    def test_detects_missing_job(self):
        broken = deepcopy(self.workflow)
        del broken["jobs"]["issue-roadmap-crawler"]
        self.assertTrue(any("missing job: issue-roadmap-crawler" in error for error in contract_errors(broken)))

    def test_detects_missing_artifact(self):
        broken = deepcopy(self.workflow)
        crawler = broken["jobs"]["issue-roadmap-crawler"]
        crawler["steps"] = [
            step for step in crawler["steps"]
            if not str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        self.assertTrue(any("artifact names changed" in error for error in contract_errors(broken)))

    def test_detects_broken_permission_and_missing_guard(self):
        broken = deepcopy(self.workflow)
        broken["jobs"]["run"]["permissions"] = {"contents": "read"}
        self.assertTrue(any("run job permissions changed" in error for error in contract_errors(broken)))

        broken = deepcopy(self.workflow)
        step = _step(broken["jobs"]["run"], "Gated TCO pipeline")
        step["if"] = "github.event_name == 'schedule'"
        self.assertTrue(any("manual-dispatch guard lost" in error for error in contract_errors(broken)))

    def test_duplicate_yaml_mapping_keys_are_rejected(self):
        with self.assertRaises(yaml.constructor.ConstructorError):
            parse_workflow(
                "permissions:\n  contents: read\npermissions:\n  contents: write\n"
            )

    def test_detects_missing_schedule_trigger(self):
        broken = deepcopy(self.workflow)
        broken["on"]["schedule"] = []
        self.assertTrue(any("heartbeat schedule" in error for error in contract_errors(broken)))

    def test_detects_guard_that_never_runs(self):
        broken = deepcopy(self.workflow)
        broken["jobs"]["issue-roadmap-crawler"]["if"] = "github.event_name == 'never'"
        self.assertTrue(any("crawler trigger condition" in error for error in contract_errors(broken)))

    def test_detects_job_level_secret_exposure(self):
        broken = deepcopy(self.workflow)
        broken["jobs"]["run"]["env"] = {"GH_TOKEN": "${{ secrets.TOKEN }}"}
        self.assertTrue(any("job-level secret exposure" in error for error in contract_errors(broken)))

    def test_detects_crawler_mutation_and_persisted_credentials(self):
        broken = deepcopy(self.workflow)
        crawler = broken["jobs"]["issue-roadmap-crawler"]
        checkout = next(
            step for step in crawler["steps"]
            if str(step.get("uses", "")).startswith("actions/checkout@")
        )
        checkout["with"]["persist-credentials"] = "true"
        self.assertTrue(any("persists credentials" in error for error in contract_errors(broken)))

        broken = deepcopy(self.workflow)
        step = _step(broken["jobs"]["issue-roadmap-crawler"], "Crawl and classify all issue states (read-only)")
        step["run"] += "\ngit push origin main\n"
        self.assertTrue(any("crawler mutation command" in error for error in contract_errors(broken)))


if __name__ == "__main__":
    unittest.main()
