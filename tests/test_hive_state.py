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

    def test_retrying_an_exhausted_vehicle_needs_a_main_queue_entry_and_a_reset(self):
        exhausted = [entry("x", attempts=3)]
        self.assertEqual(hive_state.merge_state([], [], exhausted)[0], [])
        self.assertEqual(hive_state.merge_state([task("x")], [], exhausted)[0], [])
        queue, _ = hive_state.merge_state([task("x")], [], [])
        self.assertEqual([t["variant_id"] for t in queue], ["x"])


class StateBranchTests(unittest.TestCase):
    def sh(self, *args, cwd=None):
        return subprocess.run(args, cwd=cwd, check=True, capture_output=True)

    def write(self, repo, queue, failed):
        (repo / "tasks").mkdir(exist_ok=True)
        (repo / "tasks" / "queue.json").write_text(json.dumps(queue, indent=2) + "\n")
        (repo / "tasks" / "failed.json").write_text(json.dumps(failed, indent=2) + "\n")

    def read(self, repo, name):
        return json.loads((repo / "tasks" / name).read_text())

    def remote_failed(self):
        shown = subprocess.run(["git", "show", "hive/state:tasks/failed.json"], cwd=self.origin,
                               capture_output=True, text=True, check=True).stdout
        return json.loads(shown)

    def remote_count(self):
        commits = subprocess.run(
            ["git", "log", "--first-parent", "--format=%H", "--grep=Hive-Ledger-SHA256", "hive/state"],
            cwd=self.origin, capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        return str(len(commits))

    def human_edit(self, failed):
        clone = self.tmp / "human"
        self.sh("git", "clone", "--branch", "hive/state", str(self.origin), str(clone))
        (clone / "tasks" / "failed.json").write_text(json.dumps(failed, indent=2) + "\n")
        self.sh("git", "-c", "user.name=h", "-c", "user.email=h@h", "commit", "-am", "manual fix", cwd=clone)
        self.sh("git", "push", "origin", "HEAD:refs/heads/hive/state", cwd=clone)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = self.tmp / "origin.git"
        self.sh("git", "init", "--bare", str(self.origin))
        self.a = self.tmp / "a"
        self.sh("git", "clone", str(self.origin), str(self.a))
        self.write(self.a, [task("a"), task("b")], [])
        self.sh("git", "add", ".", cwd=self.a)
        self.sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "seed", cwd=self.a)
        self.sh("git", "push", "origin", "HEAD:refs/heads/main", cwd=self.a)
        self.b = self.tmp / "b"
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
        self.assertEqual(self.remote_count(), "2")

    def test_writer_that_never_fetched_cannot_overwrite_state(self):
        self.write(self.a, [task("b")], [entry("a", attempts=1)])
        hive_state.save_state(self.a, "state 1")
        self.write(self.b, [task("a")], [])
        with self.assertRaises(subprocess.CalledProcessError):
            hive_state.save_state(self.b, "stale writer")

    def test_fetch_state_reports_missing_branch_and_leaves_files_alone(self):
        self.assertFalse(hive_state.fetch_state(self.b))
        self.assertEqual(self.read(self.b, "queue.json"), [task("a"), task("b")])

    def test_save_rejects_a_fetched_but_unreconciled_tip(self):
        self.write(self.a, [task("b")], [entry("a", attempts=2)])
        hive_state.save_state(self.a, "newer state")
        self.assertTrue(hive_state.fetch_state(self.b))
        self.write(self.b, [task("a"), task("b")], [])
        with self.assertRaises(hive_state.StateNotReconciled):
            hive_state.save_state(self.b, "stale proposal snapshot")
        self.assertEqual(self.remote_failed(), [entry("a", attempts=2)])
        self.assertEqual(self.remote_count(), "1")

    def test_reconcile_without_state_returns_none(self):
        self.assertEqual(hive_state.reconcile_with_pr(self.b), "none")

    def test_reconcile_in_sync_then_mirror_fast_forwards(self):
        self.write(self.a, [task("b")], [entry("a", attempts=1)])
        hive_state.save_state(self.a, "state 1")
        self.write(self.b, [task("b")], [entry("a", attempts=1)])
        self.assertEqual(hive_state.reconcile_with_pr(self.b), "in-sync")
        self.write(self.b, [], [entry("a", attempts=2)])
        self.assertTrue(hive_state.save_state(self.b, "mirror"))
        self.assertEqual(self.remote_failed(), [entry("a", attempts=2)])
        self.assertEqual(self.remote_count(), "2")

    def test_reconcile_heals_only_when_state_proposal_head_is_behind(self):
        self.write(self.a, [task("b"), task("a")], [entry("a", attempts=1)])
        hive_state.save_state(self.a, "state 1", proposal_head=self.sh("git", "rev-parse", "HEAD", cwd=self.a).stdout.decode().strip())
        self.write(self.b, [task("a")], [entry("a", attempts=2)])
        self.sh("git", "add", "tasks", cwd=self.b)
        self.sh("git", "-c", "user.name=p", "-c", "user.email=p@p", "commit", "-m", "proposal advanced", cwd=self.b)
        self.assertEqual(hive_state.reconcile_with_pr(self.b), "healed")
        self.assertEqual(self.remote_failed(), [entry("a", attempts=2)])
        self.assertEqual(self.remote_count(), "2")

    def test_reconcile_adopts_state_from_a_newer_proposal_head(self):
        self.write(self.a, [task("b")], [entry("a", attempts=2)])
        self.sh("git", "add", "tasks", cwd=self.a)
        self.sh("git", "-c", "user.name=p", "-c", "user.email=p@p", "commit", "-m", "newer proposal", cwd=self.a)
        hive_state.save_state(self.a, "newer proposal state", proposal_head=self.sh("git", "rev-parse", "HEAD", cwd=self.a).stdout.decode().strip())
        self.write(self.b, [task("a"), task("b")], [entry("a", attempts=1)])
        self.assertEqual(hive_state.reconcile_with_pr(self.b), "adopted")
        self.assertEqual(self.read(self.b, "queue.json"), [task("b")])
        self.assertEqual(self.read(self.b, "failed.json"), [entry("a", attempts=2)])

    def test_reconcile_does_not_restore_tasks_removed_from_state(self):
        self.write(self.a, [task("b")], [])
        hive_state.save_state(self.a, "state with deliberate removal")
        self.write(self.b, [task("a"), task("b")], [])
        self.assertEqual(hive_state.reconcile_with_pr(self.b), "adopted")
        self.assertEqual(self.read(self.b, "queue.json"), [task("b")])

    def test_reconcile_adopts_newer_retry_progress_for_same_proposal_head(self):
        self.write(self.a, [task("b")], [entry("a", attempts=2)])
        hive_state.save_state(self.a, "new retry progress")
        self.write(self.b, [task("a"), task("b")], [entry("a", attempts=1)])
        self.assertEqual(hive_state.reconcile_with_pr(self.b), "adopted")
        self.assertEqual(self.read(self.b, "failed.json"), [entry("a", attempts=2)])

    def test_reconcile_adopts_a_hand_edited_state_instead_of_overwriting_it(self):
        self.write(self.a, [task("b")], [entry("a", attempts=3)])
        hive_state.save_state(self.a, "state 1")
        self.human_edit([])
        self.write(self.b, [task("b")], [entry("a", attempts=3)])
        self.assertEqual(hive_state.reconcile_with_pr(self.b), "adopted")
        self.assertEqual(self.read(self.b, "failed.json"), [])
        self.write(self.b, [], [])
        self.assertTrue(hive_state.save_state(self.b, "mirror after adoption"))
        self.assertEqual(self.remote_failed(), [])

    def test_legacy_bot_state_with_different_ledger_fails_closed(self):
        self.write(self.a, [task("b")], [entry("a", attempts=1)])
        hive_state.save_state(self.a, "legacy precursor")
        tip = hive_state._tip(self.a)
        tree = self.sh("git", "rev-parse", f"{tip}^{{tree}}", cwd=self.a).stdout.decode().strip()
        digest = hive_state.ledger_digest(
            self.sh("git", "show", f"{tip}:tasks/failed.json", cwd=self.a).stdout,
            self.sh("git", "show", f"{tip}:tasks/queue.json", cwd=self.a).stdout,
        )
        legacy_message = f"legacy mirror\n\nHive-Ledger-SHA256: {digest}"
        legacy = self.sh("git", "commit-tree", tree, "-m", legacy_message, "-p", tip, cwd=self.a).stdout.decode().strip()
        self.sh("git", "push", "origin", f"{legacy}:refs/heads/hive/state", cwd=self.a)
        self.write(self.b, [task("a")], [entry("a", attempts=2)])
        with self.assertRaises(hive_state.StateNotReconciled):
            hive_state.reconcile_with_pr(self.b)

    def test_standalone_state_wins_when_older_proposal_is_reopened(self):
        self.sh("git", "checkout", "-b", "proposal", cwd=self.a)
        self.write(self.a, [task("b")], [entry("a", attempts=1)])
        self.sh("git", "add", "tasks", cwd=self.a)
        self.sh("git", "-c", "user.name=p", "-c", "user.email=p@p", "commit", "-m", "proposal update", cwd=self.a)
        old_proposal_head = self.sh("git", "rev-parse", "HEAD", cwd=self.a).stdout.decode().strip()
        self.sh("git", "push", "origin", "proposal", cwd=self.a)
        self.sh("git", "checkout", "--detach", old_proposal_head + "^", cwd=self.a)
        self.write(self.a, [task("b")], [entry("a", attempts=2)])
        hive_state.save_state(self.a, "standalone retry progress")
        self.sh("git", "fetch", "origin", "proposal", cwd=self.b)
        self.sh("git", "checkout", "-b", "reopened-proposal", "FETCH_HEAD", cwd=self.b)
        self.assertEqual(hive_state.reconcile_with_pr(self.b), "adopted")
        self.assertEqual(self.read(self.b, "failed.json"), [entry("a", attempts=2)])


if __name__ == "__main__":
    unittest.main()
