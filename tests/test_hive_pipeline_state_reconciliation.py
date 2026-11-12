"""End-to-end state reconciliation proof through the real Hive pipeline.

A mocked GitHub PR listing points the real pipeline at a local proposal branch.
Two cases prove that a proposal ahead of a stale state mirror is preserved, and
that a newer state mirror is adopted and propagated back to the published PR.
All Git remotes, policy, and evidence are synthetic/local.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "autonomous_pipeline.py"
sys.path.insert(0, str(ROOT / "scripts"))
import hive_state

PR_NUMBER = 777
PR_BRANCH = "hive/research-synthetic"
REPOSITORY = "CarAutopsy/carautopsy"

SITE_CUSTOMIZE = r'''
import hive_source_policy
import hive_evidence

CONFIG = {"version": 1, "approved_hosts": ["oem.example"],
          "source_policies": [{"host": "oem.example"}]}
hive_source_policy.load_policy = lambda: CONFIG
hive_source_policy.require_variant_coverage = lambda config, ids: None
hive_evidence.retrieve_approved_evidence = lambda **kwargs: []
'''

class HivePipelineStateReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hive-state-reconcile-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = self.tmp / "origin.git"
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.git("init", "--bare", str(self.origin), cwd=self.tmp)
        self.git("init", "-b", "main", str(self.repo), cwd=self.tmp)
        self.git("config", "user.name", "Hive State Test", cwd=self.repo)
        self.git("config", "user.email", "hive-state@example.invalid", cwd=self.repo)
        (self.repo / "tasks").mkdir()
        self.write_ledger([], [])
        self.git("add", ".", cwd=self.repo)
        self.git("commit", "-m", "seed synthetic pipeline repo", cwd=self.repo)
        self.git("remote", "add", "origin", str(self.origin), cwd=self.repo)
        self.git("push", "-u", "origin", "main", cwd=self.repo)

        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "if sys.argv[1:3] == ['pr', 'list']:\n"
            " print(json.dumps([{'number': 777, 'headRefName': 'hive/research-synthetic', "
            "'headRepository': {'nameWithOwner': 'CarAutopsy/carautopsy'}}]))\n"
            "else:\n"
            " raise SystemExit('unexpected gh command: ' + ' '.join(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)

        self.pipeline_dir = self.tmp / "pipeline"
        self.pipeline_dir.mkdir()
        self.pipeline = self.pipeline_dir / "autonomous_pipeline.py"
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("VERIFIED_RETRIEVAL_AVAILABLE = False", source)
        self.pipeline.write_text(
            source.replace("VERIFIED_RETRIEVAL_AVAILABLE = False",
                           "VERIFIED_RETRIEVAL_AVAILABLE = True", 1),
            encoding="utf-8",
        )
        (self.tmp / "sitecustomize.py").write_text(SITE_CUSTOMIZE, encoding="utf-8")

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(["git", *args], cwd=cwd, check=check,
                              capture_output=True, text=True)

    def write_ledger(self, queue, failed):
        (self.repo / "tasks" / "queue.json").write_text(
            json.dumps(queue, indent=2) + "\n", encoding="utf-8")
        (self.repo / "tasks" / "failed.json").write_text(
            json.dumps(failed, indent=2) + "\n", encoding="utf-8")

    def failure(self, attempts):
        return {
            "task": {"variant_id": "synthetic.model-x", "make": "Synthetic",
                     "model": "Model X"},
            "attempts": attempts, "max_attempts": 3,
            "research_attempts": 0, "max_research_attempts": 3,
            "outcome": {
                "schema_version": 1, "code": "vehicle_quality_rejection",
                "attempt_id": f"synthetic-{attempts}", "stage": "audit",
                "retryable": True, "at": "2026-11-12T00:00:00Z",
                "provider_statuses": [],
                "counters": {"provider_attempts": 0, "format_attempts": 0,
                             "provenance_attempts": 0, "attempts": attempts,
                             "research_attempts": 0},
            },
        }

    def isolated_env(self):
        env = dict(os.environ)
        for key in list(env):
            if key.startswith("GIT_") or key in {
                "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE",
                "GH_TOKEN", "GITHUB_TOKEN", "QWEN_API_KEY", "DEEPSEEK_API_KEY",
                "DEEPSEEK_API_CARAUTOPSY_KEY", "GEMINI_API_KEY",
            }:
                env.pop(key, None)
        home = self.tmp / "git-home"
        home.mkdir(exist_ok=True)
        hooks = home / "hooks"
        templates = home / "templates"
        hooks.mkdir(exist_ok=True)
        templates.mkdir(exist_ok=True)
        env.update({
            "HOME": str(home), "XDG_CONFIG_HOME": str(home / "xdg"),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TEMPLATE_DIR": str(templates),
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": str(hooks),
            "PATH": str(self.bin) + os.pathsep + env.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join((str(self.tmp), str(ROOT / "scripts"))),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        return env

    def run_pipeline(self):
        return subprocess.run(
            [sys.executable, str(self.pipeline), "--research-only"],
            cwd=self.repo, env=self.isolated_env(), capture_output=True,
            text=True, timeout=45, check=False,
        )

    def show_remote(self, ref, path):
        return json.loads(self.git("--git-dir", str(self.origin), "show",
                                   f"{ref}:{path}", cwd=self.repo).stdout)

    def proposal_head(self):
        return self.git("--git-dir", str(self.origin), "rev-parse",
                        f"refs/heads/{PR_BRANCH}", cwd=self.repo).stdout.strip()

    def test_proposal_ahead_of_stale_state_is_preserved(self):
        self.write_ledger([], [self.failure(1)])
        self.assertTrue(hive_state.save_state(self.repo, "synthetic baseline"))
        baseline = hive_state._tip(self.repo)

        self.git("checkout", "-b", PR_BRANCH, cwd=self.repo)
        self.write_ledger([], [self.failure(2)])
        self.git("add", "tasks", cwd=self.repo)
        self.git("commit", "-m", "proposal advances retry ledger", "-m",
                 f"Hive-State-Base: {baseline}", cwd=self.repo)
        self.git("push", "-u", "origin", PR_BRANCH, cwd=self.repo)

        result = self.run_pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Proposal ledger is ahead of the standalone state baseline",
                      result.stdout)
        self.assertEqual(self.show_remote(f"refs/heads/{PR_BRANCH}",
                                          "tasks/failed.json"), [self.failure(2)])
        # The stale mirror is intentionally not overwritten by the older snapshot.
        self.assertEqual(self.show_remote("refs/heads/hive/state",
                                          "tasks/failed.json"), [self.failure(1)])

    def test_newer_state_is_adopted_and_mirrored_to_published_proposal(self):
        self.git("checkout", "-b", PR_BRANCH, cwd=self.repo)
        self.write_ledger([], [self.failure(1)])
        self.git("add", "tasks", cwd=self.repo)
        self.git("commit", "-m", "published proposal baseline", "-m",
                 "Hive-State-Base: none", cwd=self.repo)
        published_head = self.git("rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        self.git("push", "-u", "origin", PR_BRANCH, cwd=self.repo)

        # Advance the local proposal ledger without updating the published PR ref.
        self.write_ledger([], [self.failure(2)])
        self.git("add", "tasks", cwd=self.repo)
        self.git("commit", "-m", "newer proposal retry progress", cwd=self.repo)
        newer_proposal_head = self.git("rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        self.assertNotEqual(published_head, newer_proposal_head)
        self.assertTrue(hive_state.save_state(
            self.repo, "mirror newer proposal progress",
            proposal_head=newer_proposal_head,
        ))

        # The fake GitHub PR still points at the old published head. Startup must
        # adopt the newer state ledger, update the PR branch, then mirror the new head.
        self.git("checkout", "--detach", published_head, cwd=self.repo)
        result = self.run_pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Adopted the ledger associated with the same or newer proposal head",
                      result.stdout)
        self.assertIn(f"Updated existing Hive research PR #{PR_NUMBER}", result.stdout)

        published_ledger = self.show_remote(f"refs/heads/{PR_BRANCH}",
                                            "tasks/failed.json")
        state_ledger = self.show_remote("refs/heads/hive/state", "tasks/failed.json")
        self.assertEqual(published_ledger, [self.failure(2)])
        self.assertEqual(state_ledger, published_ledger)
        state_tip = self.git("--git-dir", str(self.origin), "rev-parse",
                             "refs/heads/hive/state", cwd=self.repo).stdout.strip()
        recorded_head = self.git("--git-dir", str(self.origin), "log", "-1",
                                 "--format=%(trailers:key=Hive-Proposal-Head,valueonly)",
                                 state_tip, cwd=self.repo).stdout.strip()
        self.assertEqual(recorded_head, self.proposal_head())


if __name__ == "__main__":
    unittest.main()
