"""Abrupt process-interruption and restart proof for the real Hive pipeline.

A synthetic provider failure is persisted to the local hive/state remote. A Git
wrapper then SIGKILLs the pipeline immediately after the state ref is pushed,
before save_state() can finish its local bookkeeping. A fresh process must load
the durable state, recover the same task, and complete it exactly once.
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
TASK = {"variant_id": "synthetic.model-x", "make": "Synthetic", "model": "Model X"}
SOURCE_ID = "d91fac58588248c48d775c95"
URL = "https://oem.example/specs/model.html"
EVIDENCE = [{
    "source_id": SOURCE_ID,
    "url": URL,
    "retrieved_at": "2026-11-12T00:00:00Z",
    "text": "[document]\nOfficial technical specification.",
    "locator_texts": {"document": "Official technical specification."},
}]
CANDIDATE = {
    "schema_version": "1.0.0",
    "variant_id": "synthetic.model-x",
    "status": "production",
    "identity": {"make": "Synthetic", "model": "Model X"},
    "performance": {"power_w": 110000},
    "provenance": {
        "sources": [{"source_id": SOURCE_ID, "url": URL}],
        "claim_evidence": [{
            "claim_path": "performance.power_w",
            "source_id": SOURCE_ID,
            "locator": "document",
            "quote": "Official technical specification.",
        }],
    },
}

SITE_CUSTOMIZE = r'''
import json
import os
from pathlib import Path

CONFIG = {
    "version": 1,
    "approved_hosts": ["oem.example"],
    "source_policies": [{
        "host": "oem.example",
        "automated_access_allowed": True,
        "terms_url": "https://oem.example/terms",
        "terms_reviewed_at": "2026-11-01",
        "terms_reviewed_by": "synthetic-test-owner",
        "terms_review_ref": "https://github.com/CarAutopsy/carautopsy/issues/37",
        "approved_urls": [{
            "url": "https://oem.example/specs/model.html",
            "variant_ids": ["synthetic.model-x"],
        }],
    }],
}
EVIDENCE = [{
    "source_id": "d91fac58588248c48d775c95",
    "url": "https://oem.example/specs/model.html",
    "retrieved_at": "2026-11-12T00:00:00Z",
    "text": "[document]\nOfficial technical specification.",
    "locator_texts": {"document": "Official technical specification."},
}]
CANDIDATE = {
    "schema_version": "1.0.0",
    "variant_id": "synthetic.model-x",
    "status": "production",
    "identity": {"make": "Synthetic", "model": "Model X"},
    "performance": {"power_w": 110000},
    "provenance": {
        "sources": [{"source_id": "d91fac58588248c48d775c95",
                     "url": "https://oem.example/specs/model.html"}],
        "claim_evidence": [{
            "claim_path": "performance.power_w",
            "source_id": "d91fac58588248c48d775c95",
            "locator": "document",
            "quote": "Official technical specification.",
        }],
    },
}

import hive_source_policy
hive_source_policy.load_policy = lambda: CONFIG
hive_source_policy.require_variant_coverage = lambda config, ids: None

import hive_evidence
hive_evidence.retrieve_approved_evidence = lambda **kwargs: EVIDENCE

def trace(value):
    path = os.environ.get("HIVE_RETRY_TRACE")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(value + "\n")

def contract_violation(message):
    path = os.environ.get("HIVE_RETRY_VIOLATIONS")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(message + "\n")
    raise RuntimeError(message)

import requests

class SyntheticResponse:
    def __init__(self, content):
        self.content = content
    def raise_for_status(self):
        return None
    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}

def synthetic_post(url, **kwargs):
    if "dashscope" in url:
        if os.environ.get("HIVE_TEST_PROVIDER_MODE") == "fail":
            if url == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions":
                trace("qwen-intl-transport-failure")
            elif url == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions":
                trace("qwen-cn-transport-failure")
            else:
                contract_violation("unexpected Qwen endpoint: " + url)
            raise requests.exceptions.Timeout("synthetic timeout")
        # Recovery must consume the persisted failed ledger, not stale files
        # left in the shared working tree by the first subprocess.
        failed_path = Path.cwd() / "tasks" / "failed.json"
        recovered_failures = json.loads(failed_path.read_text(encoding="utf-8"))
        if len(recovered_failures) != 1:
            contract_violation("hive/state failure ledger was not restored before retry")
        prior_outcome = recovered_failures[0]["outcome"]
        if prior_outcome.get("code") != "provider_transport_failure":
            contract_violation("restored failure ledger has the wrong outcome code")
        prior_counters = prior_outcome.get("counters", {})
        expected_counters = {"provider_attempts": 1, "research_attempts": 1, "attempts": 0}
        if any(prior_counters.get(key) != value for key, value in expected_counters.items()):
            contract_violation("restored failure ledger has incorrect retry counters")
        trace("qwen-research-success")
        return SyntheticResponse(json.dumps(CANDIDATE))
    if "api.deepseek.com" in url:
        trace("deepseek-audit")
        return SyntheticResponse("PASS")
    contract_violation("unexpected provider endpoint in synthetic test: " + url)

requests.post = synthetic_post

import provider_retry
def synthetic_gemini(prompt, api_key, primary_model, fallback_model, temperature):
    trace("google-audit")
    return "PASS", primary_model
provider_retry.generate_content_with_fallback = synthetic_gemini
'''

def clean_env():
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("GIT_") or key in {
            "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE",
            "GH_TOKEN", "GITHUB_TOKEN", "QWEN_API_KEY", "DEEPSEEK_API_KEY",
            "DEEPSEEK_API_CARAUTOPSY_KEY", "GEMINI_API_KEY",
        }:
            env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class HiveRestartInterruptionProofTests(unittest.TestCase):
    def sh(self, *args, cwd, env=None):
        return subprocess.run(
            args, cwd=cwd, env=env or clean_env(), check=True,
            capture_output=True, text=True,
        )

    def pipeline_env(self, sandbox, mode, trace, interrupt=False):
        env = clean_env()
        env.update({
            "PATH": str(sandbox / "bin") + os.pathsep + env.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join((str(sandbox), str(ROOT / "scripts"))),
            "HIVE_TEST_PROVIDER_MODE": mode,
            "HIVE_RETRY_TRACE": str(trace),
            "HIVE_RETRY_VIOLATIONS": str(sandbox / "provider-violations.txt"),
        })
        if interrupt:
            env["HIVE_KILL_AFTER_STATE_PUSH"] = "1"
        if mode == "recover":
            env["DEEPSEEK_API_KEY"] = "synthetic-deepseek-key"
            env["GEMINI_API_KEY"] = "synthetic-google-key"
            env["QWEN_API_KEY"] = "synthetic-qwen-key"
        else:
            env["QWEN_API_KEY"] = "synthetic-qwen-key"
        return env

    def run_pipeline(self, repo, pipeline, env):
        return subprocess.run(
            [sys.executable, str(pipeline), "--research-only"],
            cwd=repo, env=env, capture_output=True, text=True,
            timeout=45, check=False,
        )

    def test_sigkill_after_state_push_recovers_without_duplicate_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            origin = sandbox / "origin.git"
            repo = sandbox / "work"
            repo.mkdir()
            self.sh("git", "init", "--bare", str(origin), cwd=sandbox)
            self.sh("git", "init", "-b", "main", str(repo), cwd=sandbox)
            self.sh("git", "config", "user.name", "Hive Retry Test", cwd=repo)
            self.sh("git", "config", "user.email", "hive-retry@example.invalid", cwd=repo)

            (repo / "tasks").mkdir()
            (repo / "tasks" / "queue.json").write_text(json.dumps([TASK], indent=2) + "\n", encoding="utf-8")
            (repo / "tasks" / "failed.json").write_text("[]\n", encoding="utf-8")
            (repo / "schemas").mkdir()
            shutil.copy(ROOT / "schemas" / "vehicle-variant.schema.json", repo / "schemas")
            (repo / "catalog" / "variants").mkdir(parents=True)
            self.sh("git", "add", ".", cwd=repo)
            self.sh("git", "commit", "-m", "seed retry recovery fixture", cwd=repo)
            self.sh("git", "remote", "add", "origin", str(origin), cwd=repo)
            self.sh("git", "push", "-u", "origin", "main", cwd=repo)

            bin_dir = sandbox / "bin"
            bin_dir.mkdir()
            real_git = shutil.which("git")
            self.assertIsNotNone(real_git, "git executable is required for the interruption wrapper")
            git_wrapper = bin_dir / "git"
            git_wrapper.write_text(
                "#!/usr/bin/env python3\n"
                "import os, signal, subprocess, sys\n"
                + "REAL_GIT = " + repr(real_git) + "\n"
                + "args = sys.argv[1:]\n"
                + "result = subprocess.run([REAL_GIT, *args])\n"
                + "if (result.returncode == 0 and os.environ.get('HIVE_KILL_AFTER_STATE_PUSH') == '1' "
                  "and args[:1] == ['push'] and any('refs/heads/hive/state' in arg for arg in args[1:])):\n"
                + "    os.kill(os.getppid(), signal.SIGKILL)\n"
                + "raise SystemExit(result.returncode)\n",
                encoding="utf-8",
            )
            git_wrapper.chmod(0o755)
            gh = bin_dir / "gh"
            gh.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "if sys.argv[1:3] == ['pr', 'list']:\n"
                " print('[]')\n"
                "elif sys.argv[1:3] == ['pr', 'create']:\n"
                " print('https://github.com/CarAutopsy/carautopsy/pull/999')\n"
                "else:\n"
                " raise SystemExit('unexpected gh command')\n",
                encoding="utf-8",
            )
            gh.chmod(0o755)

            pipeline_dir = sandbox / "pipeline"
            pipeline_dir.mkdir()
            pipeline = pipeline_dir / "autonomous_pipeline.py"
            source = SCRIPT.read_text(encoding="utf-8")
            self.assertIn("VERIFIED_RETRIEVAL_AVAILABLE = False", source)
            pipeline.write_text(
                source.replace(
                    "VERIFIED_RETRIEVAL_AVAILABLE = False",
                    "VERIFIED_RETRIEVAL_AVAILABLE = True",
                    1,
                ),
                encoding="utf-8",
            )
            (sandbox / "sitecustomize.py").write_text(SITE_CUSTOMIZE, encoding="utf-8")
            trace = sandbox / "provider-trace.txt"

            # First process: fail the synthetic researcher, push the retryable
            # ledger to hive/state, then SIGKILL the pipeline before save_state()
            # can update its local ref/acknowledgement.
            first = self.run_pipeline(
                repo, pipeline, self.pipeline_env(sandbox, "fail", trace, interrupt=True)
            )
            self.assertEqual(
                first.returncode, -signal.SIGKILL,
                "pipeline must be killed immediately after the hive/state ref is durably pushed; "
                + first.stdout + first.stderr,
            )
            self.assertFalse(
                (sandbox / "provider-violations.txt").exists(),
                "the synthetic provider must not report a contract violation",
            )
            self.assertFalse((repo / "catalog" / "variants" / "synthetic.model-x.json").exists())
            first_trace = trace.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                first_trace,
                ["qwen-intl-transport-failure", "qwen-cn-transport-failure"],
                "both configured Qwen endpoints must fail before the provider is classified offline",
            )

            state_queue = json.loads(self.sh(
                "git", "--git-dir", str(origin), "show",
                "refs/heads/hive/state:tasks/queue.json", cwd=repo
            ).stdout)
            state_failed = json.loads(self.sh(
                "git", "--git-dir", str(origin), "show",
                "refs/heads/hive/state:tasks/failed.json", cwd=repo
            ).stdout)
            self.assertEqual(state_queue, [TASK], "transient failure must retain the same task for retry")
            self.assertEqual(len(state_failed), 1)
            counters = state_failed[0]["outcome"]["counters"]
            self.assertEqual(state_failed[0]["outcome"]["code"], "provider_transport_failure")
            self.assertEqual(counters["provider_attempts"], 1)
            self.assertEqual(counters["research_attempts"], 1)
            self.assertEqual(counters["attempts"], 0)
            self.assertNotIn("synthetic timeout", json.dumps(state_failed), "raw provider errors must not enter the ledger")

            # Remove the local copy deliberately. The restart must restore the
            # failed outcome from hive/state after the abrupt process interruption.
            (repo / "tasks" / "failed.json").write_text("[]\\n", encoding="utf-8")

            # Restart process: reload durable state, retry the same reserved
            # identity, pass the real candidate gate and both auditors exactly once.
            second = self.run_pipeline(repo, pipeline, self.pipeline_env(sandbox, "recover", trace))
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("curated synthetic.model-x", second.stdout)
            violations = sandbox / "provider-violations.txt"
            self.assertFalse(
                violations.exists() and violations.read_text(encoding="utf-8").strip(),
                second.stdout + second.stderr + (
                    violations.read_text(encoding="utf-8") if violations.exists() else ""
                ),
            )
            second_trace = trace.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                second_trace,
                ["qwen-intl-transport-failure", "qwen-cn-transport-failure",
                 "qwen-research-success", "deepseek-audit", "google-audit"],
                second.stdout + second.stderr,
            )
            proposal_refs = self.sh(
                "git", "--git-dir", str(origin), "for-each-ref",
                "--format=%(refname)", "refs/heads/hive/research-*", cwd=repo
            ).stdout.strip().splitlines()
            self.assertEqual(len(proposal_refs), 1, "successful recovery should publish one review branch")
            proposal_ref = proposal_refs[0]
            recovered = json.loads(self.sh(
                "git", "--git-dir", str(origin), "show",
                f"{proposal_ref}:catalog/variants/synthetic.model-x.json", cwd=repo
            ).stdout)
            self.assertEqual(recovered["variant_id"], TASK["variant_id"])
            self.assertEqual(recovered["identity"], {"make": "Synthetic", "model": "Model X"})
            self.assertEqual(
                json.loads(self.sh(
                    "git", "--git-dir", str(origin), "show",
                    f"{proposal_ref}:tasks/queue.json", cwd=repo
                ).stdout),
                [],
            )
            final_queue = json.loads(self.sh(
                "git", "--git-dir", str(origin), "show",
                "refs/heads/hive/state:tasks/queue.json", cwd=repo
            ).stdout)
            final_failed = json.loads(self.sh(
                "git", "--git-dir", str(origin), "show",
                "refs/heads/hive/state:tasks/failed.json", cwd=repo
            ).stdout)
            self.assertEqual(final_queue, [])
            self.assertEqual(final_failed, [], "successful recovery must clear the prior failed outcome")


if __name__ == "__main__":
    unittest.main()
