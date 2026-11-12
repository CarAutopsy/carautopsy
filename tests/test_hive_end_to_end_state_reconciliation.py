"""Cross-process proof that a reopened proposal adopts newer durable Hive state.

The fixture uses two clones and a local bare remote. A proposal consumes a
recorded state baseline, a later standalone run advances the state mirror, and
a fresh process reopening the proposal must adopt both the newer queue and
failed ledger without losing retry progress.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hive_state


def task(variant_id):
    return {"variant_id": variant_id, "make": "Synthetic", "model": variant_id}


def failure(variant_id, attempts):
    return {
        "task": task(variant_id),
        "attempts": attempts,
        "max_attempts": 3,
        "research_attempts": 0,
        "max_research_attempts": 3,
        "outcome": {
            "schema_version": 1,
            "code": "vehicle_quality_rejection",
            "attempt_id": "synthetic-state-reconciliation",
            "stage": "audit",
            "retryable": True,
            "at": "2026-11-12T00:00:00Z",
            "provider_statuses": [],
            "counters": {
                "provider_attempts": 0,
                "format_attempts": 0,
                "provenance_attempts": 0,
                "attempts": attempts,
                "research_attempts": 0,
            },
        },
    }


class HiveEndToEndStateReconciliationTests(unittest.TestCase):
    def git_env(self, home):
        hooks = home / "hooks"
        templates = home / "templates"
        hooks.mkdir(parents=True, exist_ok=True)
        templates.mkdir(parents=True, exist_ok=True)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("GIT_")}
        env.update({
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "xdg"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TEMPLATE_DIR": str(templates),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": str(hooks),
        })
        return env

    def sh(self, *args, cwd, env):
        return subprocess.run(
            ["git", *map(str, args)], cwd=cwd, env=env,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def write_ledger(self, repo, queue, failed):
        tasks = repo / "tasks"
        tasks.mkdir(exist_ok=True)
        (tasks / "queue.json").write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
        (tasks / "failed.json").write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")

    def test_fresh_process_adopts_newer_standalone_queue_and_failed_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            env = self.git_env(home)
            origin = root / "origin.git"
            writer = root / "writer"
            reopened = root / "reopened"

            self.sh("init", "--bare", origin, cwd=root, env=env)
            writer.mkdir()
            self.sh("init", "-b", "main", writer, cwd=root, env=env)
            self.sh("config", "user.name", "Hive State Test", cwd=writer, env=env)
            self.sh("config", "user.email", "hive-state@example.invalid", cwd=writer, env=env)
            self.write_ledger(writer, [task("a"), task("b")], [])
            self.sh("add", "tasks", cwd=writer, env=env)
            self.sh("-c", "user.name=Hive State Test", "-c",
                    "user.email=hive-state@example.invalid", "commit", "-m",
                    "seed main ledger", cwd=writer, env=env)
            self.sh("remote", "add", "origin", origin, cwd=writer, env=env)
            self.sh("push", "-u", "origin", "main", cwd=writer, env=env)

            # The standalone state baseline is the exact snapshot consumed by
            # the proposal's Hive-State-Base trailer.
            with patch.dict(os.environ, env, clear=True):
                self.assertTrue(hive_state.save_state(writer, "baseline state"))
                baseline = hive_state.proposal_state_base(writer)

            proposal_branch = "hive/research-state-reconciliation"
            self.sh("checkout", "-b", proposal_branch, cwd=writer, env=env)
            proposal_queue = [task("b")]
            proposal_failed = [failure("a", 1)]
            self.write_ledger(writer, proposal_queue, proposal_failed)
            self.sh("add", "tasks", cwd=writer, env=env)
            self.sh("-c", "user.name=Hive State Test", "-c",
                    "user.email=hive-state@example.invalid", "commit",
                    "-m", "proposal ledger snapshot", "-m",
                    f"Hive-State-Base: {baseline}", cwd=writer, env=env)
            proposal_head = self.sh("rev-parse", "HEAD", cwd=writer, env=env)
            self.sh("push", "origin", proposal_branch, cwd=writer, env=env)

            # Mirror the proposal snapshot, then advance standalone state after
            # the proposal commit. The next proposal checkout must not lose it.
            with patch.dict(os.environ, env, clear=True):
                self.assertTrue(hive_state.save_state(
                    writer, "proposal state mirror", proposal_head=proposal_head
                ))
                latest_queue = [task("c"), task("b")]
                latest_failed = [failure("a", 2)]
                self.write_ledger(writer, latest_queue, latest_failed)
                self.assertTrue(hive_state.save_state(writer, "standalone retry progress"))

            self.sh("clone", "--branch", proposal_branch, origin, reopened, cwd=root, env=env)
            script = (
                "import json,sys; from pathlib import Path; "
                "import hive_state; root=Path(sys.argv[1]); "
                "result=hive_state.reconcile_with_pr(root); "
                "baseline=hive_state.proposal_state_base(root); "
                "tip=subprocess.check_output(['git','rev-parse',hive_state.STATE_REF], "
                "cwd=root, text=True).strip(); "
                "print(json.dumps({'result':result, 'tip':tip, 'baseline':baseline, "
                "'queue':json.loads((root/'tasks/queue.json').read_text()), "
                "'failed':json.loads((root/'tasks/failed.json').read_text())}))"
            )
            child_env = {
                **env,
                "PYTHONPATH": str(ROOT / "scripts"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            completed = subprocess.run(
                [sys.executable, "-c", script, str(reopened)],
                cwd=reopened, env=child_env, capture_output=True, text=True,
                check=True, timeout=30,
            )
            result_line = next(
                line for line in reversed(completed.stdout.splitlines())
                if line.startswith("{")
            )
            recovered = json.loads(result_line)
            self.assertEqual(recovered["result"], "adopted")
            self.assertEqual(recovered["queue"], latest_queue)
            self.assertEqual(recovered["failed"], latest_failed)

            # The fresh process itself must acknowledge the exact bot-written
            # state tip; a parent-process acknowledgment would not prove restart safety.
            self.assertEqual(recovered["baseline"], recovered["tip"])
            with patch.dict(os.environ, env, clear=True):
                self.assertTrue(hive_state.tip_is_bot_written(reopened, recovered["tip"]))


if __name__ == "__main__":
    unittest.main()
