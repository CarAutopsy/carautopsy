import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hive_state


def task(vid):
    return {"variant_id": vid, "make": "M", "model": vid}


def entry(vid, attempts=0, research_attempts=0):
    return {"task": task(vid), "attempts": attempts, "max_attempts": 3,
            "research_attempts": research_attempts, "max_research_attempts": 3}


class MergeStateTests(unittest.TestCase):
    def test_exhausted_ids_cover_audit_research_and_legacy_entries(self):
        failed = [entry("a", attempts=3), entry("b", research_attempts=3), entry("c", attempts=2),
                  {"task": task("legacy"), "verdict": "INDEPENDENT_AUDIT_FAILED"}]
        self.assertEqual(hive_state.exhausted_ids(failed), {"a", "b"})

    def test_state_order_wins_and_main_only_entries_are_appended(self):
        queue, failed = hive_state.merge_state(
            [task("a"), task("b"), task("new")], [task("b"), task("a")], [entry("a", attempts=1)])
        self.assertEqual([t["variant_id"] for t in queue], ["b", "a", "new"])
        self.assertEqual(failed, [entry("a", attempts=1)])

    def test_exhausted_vehicles_are_not_requeued_from_main(self):
        queue, _ = hive_state.merge_state([task("a"), task("b")], [task("b")], [entry("a", attempts=3)])
        self.assertEqual([t["variant_id"] for t in queue], ["b"])


class StateBranchTests(unittest.TestCase):
    def sh(self, *args, cwd=None):
        return subprocess.run(args, cwd=cwd, check=True, capture_output=True)

    def write(self, repo, queue, failed):
        (repo / "tasks").mkdir(exist_ok=True)
        (repo / "tasks" / "queue.json").write_text(json.dumps(queue, indent=2) + "\n")
        (repo / "tasks" / "failed.json").write_text(json.dumps(failed, indent=2) + "\n")

    def read(self, repo, name):
        return json.loads((repo / "tasks" / name).read_text())

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        self.origin = tmp / "origin.git"
        self.sh("git", "init", "--bare", str(self.origin))
        self.a = tmp / "a"
        self.sh("git", "clone", str(self.origin), str(self.a))
        self.write(self.a, [task("a"), task("b")], [])
        self.sh("git", "add", ".", cwd=self.a)
        self.sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "seed", cwd=self.a)
        self.sh("git", "push", "origin", "HEAD:refs/heads/main", cwd=self.a)
        self.b = tmp / "b"
        self.sh("git", "clone", "--branch", "main", str(self.origin), str(self.b))

    def test_load_without_branch_leaves_main_ledger(self):
        self.assertFalse(hive_state.load_state(self.b))
        self.assertEqual(self.read(self.b, "queue.json"), [task("a"), task("b")])

    def test_save_then_load_round_trip_in_another_clone(self):
        self.write(self.a, [task("b"), task("a")], [entry("a", attempts=1)])
        self.assertTrue(hive_state.save_state(self.a, "state 1"))
        self.assertFalse(hive_state.save_state(self.a, "state 1 again"))
        self.assertTrue(hive_state.load_state(self.b))
        self.assertEqual([t["variant_id"] for t in self.read(self.b, "queue.json")], ["b", "a"])
        self.assertEqual(self.read(self.b, "failed.json"), [entry("a", attempts=1)])

    def test_state_branch_holds_only_ledger_files_and_second_save_fast_forwards(self):
        self.write(self.a, [task("b")], [entry("a", attempts=3)])
        hive_state.save_state(self.a, "state 1")
        self.write(self.a, [], [entry("a", attempts=3), entry("b", attempts=3)])
        self.assertTrue(hive_state.save_state(self.a, "state 2"))
        files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "hive/state"], cwd=self.origin,
                               capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(sorted(files), ["tasks/failed.json", "tasks/queue.json"])
        count = subprocess.run(["git", "rev-list", "--count", "hive/state"], cwd=self.origin,
                               capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(count, "2")

    def test_writer_without_loaded_state_cannot_overwrite_it(self):
        self.write(self.a, [task("b")], [entry("a", attempts=1)])
        hive_state.save_state(self.a, "state 1")
        self.write(self.b, [task("a")], [])
        with self.assertRaises(subprocess.CalledProcessError):
            hive_state.save_state(self.b, "stale writer")


if __name__ == "__main__":
    unittest.main()
