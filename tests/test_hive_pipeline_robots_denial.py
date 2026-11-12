"""Subprocess proof that a real robots.txt denial pauses Hive before mutation.

The test enables the research path only in a temporary pipeline copy, supplies
an owner-shaped synthetic policy, and runs the real robots parser against a
synthetic robots.txt response. No DNS lookup, OEM request, or provider call is
permitted by the test harness.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "autonomous_pipeline.py"
REPO_LOCATION_ENV_VARS = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"}


def sanitized_env():
    return {key: value for key, value in os.environ.items() if key not in REPO_LOCATION_ENV_VARS}

SITE_CUSTOMIZE = r"""
import os
from pathlib import Path
from types import SimpleNamespace

import hive_source_policy

SOURCE_URL = "https://oem.example/specs/car.html"
ROBOTS_URL = "https://oem.example/robots.txt"
POLICY = {
    "version": 1,
    "approved_hosts": ["oem.example"],
    "source_policies": [{
        "host": "oem.example",
        "automated_access_allowed": True,
        "terms_url": "https://oem.example/terms",
        "terms_reviewed_at": "2026-11-11",
        "terms_reviewed_by": "synthetic-test-owner",
        "terms_review_ref": "https://github.com/CarAutopsy/carautopsy/issues/37",
        "approved_urls": [{
            "url": SOURCE_URL,
            "variant_ids": ["main-task", "proposal-task", "state-task"],
        }],
    }],
}
hive_source_policy.load_policy = lambda: POLICY

# Keep the production policy implementation and parser. Replace only the
# transport boundary for the robots bootstrap with a deterministic response.
import hive_evidence
real_check_source_access = hive_source_policy.check_source_access

def synthetic_robots_fetcher(url, *, approved_hosts, robots_allowed, **kwargs):
    marker = os.environ.get("HIVE_ROBOTS_REQUEST_MARKER")
    if marker:
        Path(marker).write_text(url, encoding="utf-8")
    if url != ROBOTS_URL or robots_allowed(url) is not True:
        raise AssertionError("test attempted a non-robots policy request")
    return SimpleNamespace(
        outcome="retrieved_unverified",
        body=b"User-agent: *\nDisallow: /specs/\n",
    )

def check_source_access_with_synthetic_robots(url, *, config, fetcher, today=None):
    try:
        return real_check_source_access(
            url,
            config=config,
            fetcher=synthetic_robots_fetcher,
            today=today,
        )
    except hive_source_policy.SourcePolicyDenied as exc:
        marker = os.environ.get("HIVE_ROBOTS_DECISION_MARKER")
        if marker:
            Path(marker).write_text(str(exc), encoding="utf-8")
        raise

hive_evidence.check_source_access = check_source_access_with_synthetic_robots

# A bug that skips the robots check must not fall through to real networking.
# The retrieval adapter's default fetcher is keyword-only and is bound at
# function definition time, so replace that bound default explicitly.
def forbidden_target_fetcher(url, **kwargs):
    marker = os.environ.get("HIVE_TARGET_REQUEST_MARKER")
    if marker:
        Path(marker).write_text(url, encoding="utf-8")
    raise AssertionError("target document fetch must not follow robots denial")

hive_evidence.retrieve_approved_evidence.__kwdefaults__["fetcher"] = forbidden_target_fetcher

# Provider calls are also tripwired. The test supplies only a synthetic key.
try:
    import requests
    def forbidden_provider_call(*args, **kwargs):
        marker = os.environ.get("HIVE_PROVIDER_CALL_MARKER")
        if marker:
            Path(marker).write_text("called", encoding="utf-8")
        raise AssertionError("provider call reached after robots denial")
    requests.post = forbidden_provider_call
except ImportError:
    pass
"""


class PipelineRobotsDenialTests(unittest.TestCase):
    def sh(self, *args, cwd, env=None):
        return subprocess.run(
            args, cwd=cwd, env=env if env is not None else sanitized_env(),
            check=True, capture_output=True, text=True
        )

    def write_queue(self, repo, variant_id):
        path = repo / "tasks" / "queue.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        queue = [] if variant_id is None else [{
            "variant_id": variant_id, "make": "Synthetic", "model": variant_id,
        }]
        path.write_text(json.dumps(queue) + "\n", encoding="utf-8")
        (repo / "tasks" / "failed.json").write_text("[]\n", encoding="utf-8")

    def tree_hashes(self, root):
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(root).parts
        }

    def test_robots_denial_precedes_proposal_checkout_state_overlay_and_provider_calls(self):
        for scenario in ("main-task", "state-task", "proposal-task"):
            with self.subTest(denied_queue=scenario):
                with tempfile.TemporaryDirectory() as directory:
                    sandbox = Path(directory)
                    origin = sandbox / "origin.git"
                    repo = sandbox / "work"
                    repo.mkdir()
                    self.sh("git", "init", "--bare", str(origin), cwd=sandbox)
                    self.sh("git", "init", "-b", "main", str(repo), cwd=sandbox)
                    self.sh("git", "config", "user.name", "Hive Test", cwd=repo)
                    self.sh("git", "config", "user.email", "hive-test@example.invalid", cwd=repo)
                    self.write_queue(repo, "main-task" if scenario == "main-task" else None)
                    (repo / "tasks" / "fixture-branch.txt").write_text("main\n", encoding="utf-8")
                    self.sh("git", "add", "tasks", cwd=repo)
                    self.sh("git", "commit", "-m", "seed main queue", cwd=repo)
                    self.sh("git", "remote", "add", "origin", str(origin), cwd=repo)
                    self.sh("git", "push", "-u", "origin", "main", cwd=repo)
        
                    # Distinct remote proposal and hive/state snapshots expose premature
                    # checkout or state overlay as observable mutations.
                    self.sh("git", "checkout", "-b", "hive/research-fixture", cwd=repo)
                    self.write_queue(repo, "proposal-task" if scenario == "proposal-task" else None)
                    (repo / "tasks" / "fixture-branch.txt").write_text("proposal\n", encoding="utf-8")
                    self.sh("git", "add", "tasks", cwd=repo)
                    self.sh("git", "commit", "-m", "seed proposal queue", cwd=repo)
                    self.sh("git", "push", "origin", "hive/research-fixture", cwd=repo)
        
                    self.sh("git", "checkout", "main", cwd=repo)
                    self.sh("git", "checkout", "-b", "hive/state", cwd=repo)
                    self.write_queue(repo, "state-task" if scenario == "state-task" else None)
                    (repo / "tasks" / "fixture-branch.txt").write_text("state\n", encoding="utf-8")
                    self.sh("git", "add", "tasks", cwd=repo)
                    self.sh("git", "commit", "-m", "seed state queue", cwd=repo)
                    self.sh("git", "push", "origin", "hive/state", cwd=repo)
                    self.sh("git", "checkout", "main", cwd=repo)
        
                    # Fake only GitHub CLI discovery; Git operations use the local bare
                    # remote and therefore exercise the real pipeline's branch logic.
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
        
                    robots_marker = sandbox / "robots-request.marker"
                    decision_marker = sandbox / "robots-decision.marker"
                    target_marker = sandbox / "target-request.marker"
                    provider_marker = sandbox / "provider-request.marker"
                    env = sanitized_env()
                    env.update({
                        "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
                        "PYTHONPATH": os.pathsep.join((str(sandbox), str(ROOT / "scripts"))),
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "HIVE_ROBOTS_REQUEST_MARKER": str(robots_marker),
                        "HIVE_ROBOTS_DECISION_MARKER": str(decision_marker),
                        "HIVE_DENIED_VARIANT_ID": scenario,
                        "HIVE_TARGET_REQUEST_MARKER": str(target_marker),
                        "HIVE_PROVIDER_CALL_MARKER": str(provider_marker),
                        "QWEN_API_KEY": "synthetic-not-a-real-key",
                    })
                    before = self.tree_hashes(repo)
                    remote_refs_before = self.sh(
                        "git", "--git-dir", str(origin), "for-each-ref",
                        "--format=%(refname) %(objectname)", "refs/heads", cwd=repo
                    ).stdout.strip()
                    state_ref_before = self.sh(
                        "git", "--git-dir", str(origin), "rev-parse",
                        "refs/heads/hive/state", cwd=repo
                    ).stdout.strip()
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
                    self.assertTrue(robots_marker.exists(), "the synthetic robots.txt policy was not checked")
                    self.assertEqual(
                        robots_marker.read_text(encoding="utf-8"),
                        "https://oem.example/robots.txt",
                    )
                    self.assertTrue(decision_marker.exists(), "the production robots policy did not record a denial")
                    self.assertEqual(
                        decision_marker.read_text(encoding="utf-8"),
                        "robots.txt disallows this exact source URL",
                        "the pipeline paused for something other than an exact robots.txt denial",
                    )
                    self.assertFalse(target_marker.exists(), "target document fetched despite robots denial")
                    self.assertFalse(provider_marker.exists(), "a paid provider was called after robots denial")
                    self.assertEqual(
                        self.sh("git", "branch", "--show-current", cwd=repo).stdout.strip(),
                        branch_before,
                        "the pipeline checked out the proposal before robots denial stopped preflight",
                    )
                    self.assertEqual(
                        self.tree_hashes(repo),
                        before,
                        "robots denial changed the working tree or Hive ledger",
                    )
                    remote_refs_after = self.sh(
                        "git", "--git-dir", str(origin), "for-each-ref",
                        "--format=%(refname) %(objectname)", "refs/heads", cwd=repo
                    ).stdout.strip()
                    self.assertEqual(remote_refs_after, remote_refs_before, "robots denial changed a bare remote branch")
                    state_ref_after = self.sh(
                        "git", "--git-dir", str(origin), "rev-parse",
                        "refs/heads/hive/state", cwd=repo
                    ).stdout.strip()
                    self.assertEqual(state_ref_after, state_ref_before, "robots denial changed the remote hive/state ref")
                    expected_state_queue = [] if scenario != "state-task" else [{
                        "variant_id": "state-task", "make": "Synthetic", "model": "state-task",
                    }]
                    self.assertEqual(
                        json.loads(self.sh(
                            "git", "--git-dir", str(origin), "show",
                            "refs/heads/hive/state:tasks/queue.json", cwd=repo
                        ).stdout),
                        expected_state_queue,
                        "robots denial changed the queue stored in the bare remote",
                    )


if __name__ == "__main__":
    unittest.main()
