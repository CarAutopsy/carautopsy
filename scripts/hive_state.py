"""Persist the Hive queue and failed ledger on a dedicated state branch.

The state branch never touches main or the catalog. It lets research batches
that produce no catalog changes keep their retry counters without opening a
review PR. While a proposal PR is open the PR branch carries the ledger and
the state branch only mirrors it, so the two never diverge.
"""
import json
import os
import subprocess
from pathlib import Path

STATE_BRANCH = "hive/state"
STATE_REF = "refs/remotes/origin/hive/state"
QUEUE = "tasks/queue.json"
FAILED = "tasks/failed.json"
DEFAULT_MAX_ATTEMPTS = 3


def _git(root, args, input_bytes=None, env=None, check=True):
    return subprocess.run(["git", *args], cwd=root, input=input_bytes,
                          capture_output=True, check=check, env=env)


def exhausted_ids(failed):
    """Variant ids whose audit or research retry budget is used up."""
    ids = set()
    for item in failed:
        vid = (item.get("task") or {}).get("variant_id")
        if not vid:
            continue
        audit_limit = int(item.get("max_attempts") or DEFAULT_MAX_ATTEMPTS)
        research_limit = int(item.get("max_research_attempts") or DEFAULT_MAX_ATTEMPTS)
        if (int(item.get("attempts") or 0) >= audit_limit
                or int(item.get("research_attempts") or 0) >= research_limit):
            ids.add(vid)
    return ids


def merge_state(main_queue, state_queue, state_failed):
    """State wins; add queue entries only present on main unless exhausted."""
    blocked = exhausted_ids(state_failed)
    queue = list(state_queue)
    seen = {task.get("variant_id") for task in queue}
    for task in main_queue:
        vid = task.get("variant_id")
        if vid and vid not in seen and vid not in blocked:
            queue.append(task)
            seen.add(vid)
    return queue, list(state_failed)


def remote_has_state(root):
    result = _git(root, ["ls-remote", "--exit-code", "--heads", "origin", STATE_BRANCH], check=False)
    if result.returncode == 0:
        return True
    if result.returncode == 2:
        return False
    raise RuntimeError("could not query origin for the Hive state branch")


def fetch_state(root):
    """Fetch the state branch into a local ref without touching the working tree."""
    if not remote_has_state(root):
        return False
    _git(root, ["fetch", "origin", f"+{STATE_BRANCH}:{STATE_REF}"])
    return True


def load_state(root):
    """Overlay the saved ledger onto the working tree. Returns True if loaded."""
    root = Path(root)
    if not fetch_state(root):
        print("No Hive state branch yet; using the ledger on main.")
        return False
    state_queue = json.loads(_git(root, ["show", f"{STATE_REF}:{QUEUE}"]).stdout)
    state_failed = json.loads(_git(root, ["show", f"{STATE_REF}:{FAILED}"]).stdout)
    queue_path = root / QUEUE
    main_queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
    queue, failed = merge_state(main_queue, state_queue, state_failed)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
    (root / FAILED).write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
    print(f"Loaded Hive state: {len(queue)} queued, {len(failed)} ledger entries.")
    return True


def _tip(root):
    result = _git(root, ["rev-parse", "--verify", "-q", STATE_REF], check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def save_state(root, message):
    """Commit the working-tree ledger to the state branch. Returns True if pushed.

    Uses git plumbing so the working tree, index and current branch are untouched.
    The push is a fast-forward only; a concurrent writer makes it fail closed.
    """
    root = Path(root)
    blobs = {}
    for rel in (FAILED, QUEUE):
        path = root / rel
        data = path.read_bytes() if path.exists() else b"[]\n"
        blobs[rel] = _git(root, ["hash-object", "-w", "--stdin"], input_bytes=data).stdout.decode().strip()
    tip = _tip(root)
    if tip:
        same = all(
            _git(root, ["rev-parse", f"{tip}:{rel}"], check=False).stdout.decode().strip() == sha
            for rel, sha in blobs.items()
        )
        if same:
            return False
    listing = (f"100644 blob {blobs[FAILED]}\tfailed.json\n"
               f"100644 blob {blobs[QUEUE]}\tqueue.json\n").encode()
    tasks_tree = _git(root, ["mktree"], input_bytes=listing).stdout.decode().strip()
    root_tree = _git(root, ["mktree"], input_bytes=f"040000 tree {tasks_tree}\ttasks\n".encode()).stdout.decode().strip()
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "hive-bot", "GIT_AUTHOR_EMAIL": "hive-bot@users.noreply.github.com",
           "GIT_COMMITTER_NAME": "hive-bot", "GIT_COMMITTER_EMAIL": "hive-bot@users.noreply.github.com"}
    args = ["commit-tree", root_tree, "-m", message]
    if tip:
        args += ["-p", tip]
    commit = _git(root, args, env=env).stdout.decode().strip()
    _git(root, ["push", "origin", f"{commit}:refs/heads/{STATE_BRANCH}"])
    _git(root, ["update-ref", STATE_REF, commit])
    return True
