"""Integration proof that evidence preflight failure precedes proposal/state mutation.

The subprocess runs the real pipeline entry point with retrieval deliberately
failed at the evidence adapter boundary. Git remotes and provider calls are
local fakes; no network retrieval or paid provider call is made.
"""
import hashlib
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

SITE_CUSTOMIZE = r"""
import os
from pathlib import Path

import hive_source_policy
hive_source_policy.load_policy = lambda: {
    "version": 1,
    "approved_hosts": ["oem.example"],
    "source_policies": [{"host": "oem.example", "approved_urls": []}],
}
hive_source_policy.require_variant_coverage = lambda config, variant_ids: None

import hive_evidence
def fail_closed_retrieval(*, variant_id, config):
    marker = os.environ.get("HIVE_RETRIEVAL_MARKER")
    if marker:
        Path(marker).write_text(variant_id, encoding="utf-8")
    raise RuntimeError("synthetic retrieval failure")
hive_evidence.retrieve_approved_evidence = fail_closed_retrieval
"""


class PipelinePreflightFailureTests(unittest.TestCase):
    def sh(self, *args, cwd, env=None):
        return subprocess.run(
            args, cwd=cwd, env=env, check=True, capture_output=True, text=True
        )

    def write_queue(self, repo, variant_id):
        path = repo / "tasks" / "queue.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([{
                "variant_id": variant_id,
                "make": "Synthetic",
                "model": variant_id,
            }]) + "\n",
            encoding="utf-8",
        )
        failed = repo / "tasks" / "failed.json"
        failed.write_text("[]\n", encoding="utf-8")

    def tree_hashes(self, root):
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(root).parts
        }

    def test_retrieval_failure_does_not_checkout_proposal_or_overlay_state(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            origin = sandbox / "origin.git"
            repo = sandbox / "work"
            repo.mkdir()
            self.sh("git", "init", "--bare", str(origin), cwd=sandbox)
            self.sh("git", "init", "-b", "main", str(repo), cwd=sandbox)
            self.sh("git", "config", "user.name", "Hive Test", cwd=repo)
            self.sh("git", "config", "user.email", "hive-test@example.invalid", cwd=repo)
            self.write_queue(repo, "main-task")
            self.sh("git", "add", "tasks", cwd=repo)
            self.sh("git", "commit", "-m", "seed main queue", cwd=repo)
            self.sh("git", "remote", "add", "origin", str(origin), cwd=repo)
            self.sh("git", "push", "-u", "origin", "main", cwd=repo)

            # A proposal branch and a distinct state branch both exist remotely.
            self.sh("git", "checkout", "-b", "hive/research-fixture", cwd=repo)
            self.write_queue(repo, "proposal-task")
            self.sh("git", "add", "tasks", cwd=repo)
            self.sh("git", "commit", "-m", "seed proposal queue", cwd=repo)
            self.sh("git", "push", "origin", "hive/research-fixture", cwd=repo)

            self.sh("git", "checkout", "main", cwd=repo)
            self.sh("git", "checkout", "-b", "hive/state", cwd=repo)
            self.write_queue(repo, "state-task")
            self.sh("git", "add", "tasks", cwd=repo)
            self.sh("git", "commit", "-m", "seed state queue", cwd=repo)
            self.sh("git", "push", "origin", "hive/state", cwd=repo)
            self.sh("git", "checkout", "main", cwd=repo)

            # Fake only the GitHub CLI listing. Git fetch/show operate against
            # the local bare remote created above.
            bin_dir = sandbox / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "print(json.dumps([{\"number\": 999, "
                "\"headRefName\": \"hive/research-fixture\", "
                "\"headRepository\": {\"nameWithOwner\": \"CarAutopsy/carautopsy\"}}]))\n",
                encoding="utf-8",
            )
            gh.chmod(0o755)

            script_dir = sandbox / "scripts"
            script_dir.mkdir()
            pipeline_copy = script_dir / "autonomous_pipeline.py"
            source = SCRIPT.read_text(encoding="utf-8")
            self.assertIn("VERIFIED_RETRIEVAL_AVAILABLE = False", source)
            pipeline_copy.write_text(
                source.replace(
                    "VERIFIED_RETRIEVAL_AVAILABLE = False",
                    "VERIFIED_RETRIEVAL_AVAILABLE = True",
                    1,
                ),
                encoding="utf-8",
            )
            (sandbox / "sitecustomize.py").write_text(SITE_CUSTOMIZE, encoding="utf-8")

            retrieval_marker = sandbox / "retrieval-called.marker"
            provider_marker = sandbox / "provider-called.marker"
            env = os.environ.copy()
            env.update({
                "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
                "PYTHONPATH": os.pathsep.join((str(sandbox), str(ROOT / "scripts"))),
                "PYTHONDONTWRITEBYTECODE": "1",
                "HIVE_RETRIEVAL_MARKER": str(retrieval_marker),
                "HIVE_PROVIDER_CALL_MARKER": str(provider_marker),
                "QWEN_API_KEY": "synthetic-not-a-real-key",
            })
            before = self.tree_hashes(repo)
            branch_before = self.sh(
                "git", "branch", "--show-current", cwd=repo
            ).stdout.strip()

            result = subprocess.run(
                [sys.executable, str(pipeline_copy), "--research-only"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("HIVE_RESEARCH_PAUSED:", result.stderr)
            self.assertTrue(retrieval_marker.exists(), "the synthetic retrieval failure was not reached")
            self.assertFalse(provider_marker.exists(), "a provider was called after retrieval failed")
            self.assertEqual(
                self.sh("git", "branch", "--show-current", cwd=repo).stdout.strip(),
                branch_before,
                "the pipeline checked out the proposal before evidence preflight succeeded",
            )
            self.assertEqual(
                self.tree_hashes(repo),
                before,
                "the failed preflight changed the working tree or Hive ledger",
            )
            self.assertEqual(
                self.sh("git", "show", "hive/state:tasks/queue.json", cwd=repo).stdout.strip(),
                json.dumps([{"variant_id": "state-task", "make": "Synthetic", "model": "state-task"}]),
            )


if __name__ == "__main__":
    unittest.main()
