"""Persist the Hive queue and failed ledger on a dedicated state branch.

The state branch never touches main or the catalog. It lets research batches
that produce no catalog changes keep their retry counters without opening a
review PR. While a proposal PR is open the PR branch carries the ledger and
the state branch mirrors it.

Safety rules:
- Every state commit carries a Hive-Ledger-SHA256 trailer. A tip whose content
  does not match its own trailer (or has none) was edited by hand, and a hand
  edit wins over the bot's snapshot.
- save_state() refuses to write on top of a fetched tip whose ledger was never
  loaded or reconciled in this process, so a stale snapshot cannot overwrite a
  newer state.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

STATE_BRANCH = "hive/state"
STATE_REF = "refs/remotes/origin/hive/state"
QUEUE = "tasks/queue.json"
FAILED = "tasks/failed.json"
DEFAULT_MAX_ATTEMPTS = 3
TRAILER = "Hive-Ledger-SHA256"
PROPOSAL_HEAD_TRAILER = "Hive-Proposal-Head"
STATE_CONTEXT_TRAILER = "Hive-State-Context"
PROPOSAL_STATE_BASE_TRAILER = "Hive-State-Base"

_ACKNOWLEDGED = {}


class StateNotReconciled(RuntimeError):
    """The fetched state tip was never merged into the working ledger."""


def _git(root, args, input_bytes=None, env=None, check=True):
    return subprocess.run(["git", *args], cwd=root, input=input_bytes,
                          capture_output=True, check=check, env=env)


def _key(root):
    return str(Path(root).resolve())


def _ack(root, tip):
    _ACKNOWLEDGED[_key(root)] = tip


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
    """State wins; add queue entries only present on main unless exhausted.

    To retry an exhausted vehicle: put its task on main's queue and remove or
    reset its entry in the state branch's failed.json.
    """
    blocked = exhausted_ids(state_failed)
    queue = list(state_queue)
    seen = {task.get("variant_id") for task in queue}
    for task in main_queue:
        vid = task.get("variant_id")
        if vid and vid not in seen and vid not in blocked:
            queue.append(task)
            seen.add(vid)
    return queue, list(state_failed)


def ledger_digest(failed_bytes, queue_bytes):
    digest = hashlib.sha256()
    digest.update(failed_bytes)
    digest.update(b"\0")
    digest.update(queue_bytes)
    return digest.hexdigest()


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


def _tip(root):
    result = _git(root, ["rev-parse", "--verify", "-q", STATE_REF], check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def _tip_files(root, tip):
    files = {}
    for rel in (FAILED, QUEUE):
        result = _git(root, ["show", f"{tip}:{rel}"], check=False)
        files[rel] = result.stdout if result.returncode == 0 else None
    return files


def _declared_digest(root, tip):
    body = _git(root, ["log", "-1", "--format=%B", tip]).stdout.decode()
    for line in body.splitlines():
        if line.startswith(TRAILER + ":"):
            return line.split(":", 1)[1].strip()
    return None


def tip_is_bot_written(root, tip):
    files = _tip_files(root, tip)
    declared = _declared_digest(root, tip)
    if declared is None or any(content is None for content in files.values()):
        return False
    return ledger_digest(files[FAILED], files[QUEUE]) == declared


def _declared_proposal_head(root, tip):
    body = _git(root, ["log", "-1", "--format=%B", tip]).stdout.decode()
    for line in body.splitlines():
        if line.startswith(PROPOSAL_HEAD_TRAILER + ":"):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def _declared_state_context(root, tip):
    body = _git(root, ["log", "-1", "--format=%B", tip]).stdout.decode()
    for line in body.splitlines():
        if line.startswith(STATE_CONTEXT_TRAILER + ":"):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def _declared_proposal_state_base(root, proposal_head):
    body = _git(root, ["log", "-1", "--format=%B", proposal_head]).stdout.decode()
    for line in body.splitlines():
        if line.startswith(PROPOSAL_STATE_BASE_TRAILER + ":"):
            value = line.split(":", 1)[1].strip()
            return None if value == "none" else (value or None)
    return None


def proposal_state_base(root):
    """Return the reconciled hive/state tip that the next proposal commit consumes."""
    root = Path(root)
    tip = _tip(root)
    if tip and _ACKNOWLEDGED.get(_key(root)) != tip:
        raise StateNotReconciled(
            "cannot record proposal baseline before hive/state has been reconciled"
        )
    return tip


def _write_state_files(root, files):
    if any(content is None for content in files.values()):
        raise RuntimeError("Hive state tip is missing a required ledger file")
    for rel, content in files.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _is_ancestor(root, older, newer):
    result = _git(root, ["merge-base", "--is-ancestor", older, newer], check=False)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError("could not compare Hive proposal history")


def _overlay(root):
    root = Path(root)
    state_queue = json.loads(_git(root, ["show", f"{STATE_REF}:{QUEUE}"]).stdout)
    state_failed = json.loads(_git(root, ["show", f"{STATE_REF}:{FAILED}"]).stdout)
    queue_path = root / QUEUE
    main_queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
    queue, failed = merge_state(main_queue, state_queue, state_failed)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
    (root / FAILED).write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
    return len(queue), len(failed)


def load_state(root):
    """Overlay the saved ledger onto the working tree. Returns True if loaded."""
    root = Path(root)
    if not fetch_state(root):
        print("No Hive state branch yet; using the ledger on main.")
        return False
    queued, entries = _overlay(root)
    _ack(root, _tip(root))
    print(f"Loaded Hive state: {queued} queued, {entries} ledger entries.")
    return True


def reconcile_with_pr(root):
    """Reconcile a proposal ledger against the proposal head recorded in hive/state.

    A state mirror records the proposal commit whose ledger it contains. If that
    commit is behind the checked-out proposal, the proposal ledger may heal the
    mirror. If it is equal to or ahead of the checkout, state wins. Divergent
    histories fail closed rather than guessing which retry progress is newer.

    State is authoritative for an open proposal's queue: do not merge missing
    tasks back from the proposal branch, because their absence may be deliberate.
    Returns "none", "in-sync", "adopted" or "healed".
    """
    root = Path(root)
    if not fetch_state(root):
        return "none"
    tip = _tip(root)
    files = _tip_files(root, tip)
    if not tip_is_bot_written(root, tip):
        _write_state_files(root, files)
        _ack(root, tip)
        print("Hive state was edited by hand; adopted its queue and failed ledger exactly.")
        return "adopted"

    recorded_head = _declared_proposal_head(root, tip)
    state_context = _declared_state_context(root, tip)
    current_head = _git(root, ["rev-parse", "HEAD"]).stdout.decode().strip()
    working = {}
    for rel in (FAILED, QUEUE):
        path = root / rel
        working[rel] = path.read_bytes() if path.exists() else b"[]\n"

    if state_context == "standalone":
        if working == files:
            _ack(root, tip)
            return "in-sync"
        state_base = _declared_proposal_state_base(root, current_head)
        if not state_base:
            raise StateNotReconciled(
                "proposal has no verifiable Hive-State-Base; refusing to adopt standalone state"
            )
        if tip == state_base or _is_ancestor(root, tip, state_base):
            # The proposal already consumed this state snapshot. A failed mirror
            # push must not let that older snapshot erase the proposal ledger.
            _ack(root, tip)
            print("Proposal ledger is ahead of the standalone state baseline; preserving proposal progress.")
            return "proposal-ahead"
        if _is_ancestor(root, state_base, tip):
            _write_state_files(root, files)
            _ack(root, tip)
            print("Adopted standalone Hive progress committed after the proposal baseline.")
            return "adopted"
        raise StateNotReconciled(
            "standalone Hive state is not descended from the proposal's recorded baseline; "
            "refusing an ambiguous reconciliation"
        )

    if state_context == "proposal":
        if not recorded_head:
            raise StateNotReconciled("proposal state is missing its recorded proposal HEAD")
        if recorded_head != current_head and _is_ancestor(root, recorded_head, current_head):
            _ack(root, tip)
            print("Hive state references an older proposal head; healing from the newer proposal ledger.")
            save_state(root, "chore(hive-state): heal from newer proposal head",
                       proposal_head=current_head)
            return "healed"
        if recorded_head != current_head and not _is_ancestor(root, current_head, recorded_head):
            raise StateNotReconciled(
                "Hive state and checked-out proposal have divergent histories; refusing to overwrite either ledger"
            )
        if working == files:
            _ack(root, tip)
            return "in-sync"
        _write_state_files(root, files)
        _ack(root, tip)
        print("Adopted the ledger associated with the same or newer proposal head.")
        return "adopted"

    if working == files:
        _ack(root, tip)
        return "in-sync"
    raise StateNotReconciled(
        "legacy Hive state has no context metadata and differs from the proposal ledger; "
        "refusing an ambiguous reconciliation"
    )


def save_state(root, message, proposal_head=None):
    """Commit the working-tree ledger to the state branch. Returns True if pushed.

    Uses git plumbing so the working tree, index and current branch are untouched.
    Refuses to build on a fetched tip that was not loaded or reconciled, and the
    push is fast-forward only, so a concurrent writer also fails closed.
    """
    root = Path(root)
    tip = _tip(root)
    if tip and _ACKNOWLEDGED.get(_key(root)) != tip:
        raise StateNotReconciled(
            "hive/state was fetched but its ledger was not loaded or reconciled; "
            "refusing to overwrite it with a possibly stale snapshot")

    contents = {}
    blobs = {}
    for rel in (FAILED, QUEUE):
        path = root / rel
        contents[rel] = path.read_bytes() if path.exists() else b"[]\n"
        blobs[rel] = _git(root, ["hash-object", "-w", "--stdin"],
                          input_bytes=contents[rel]).stdout.decode().strip()

    digest = ledger_digest(contents[FAILED], contents[QUEUE])
    if proposal_head is not None:
        proposal_head = str(proposal_head)
    if tip:
        same_ledger = all(
            _git(root, ["rev-parse", f"{tip}:{rel}"], check=False).stdout.decode().strip() == sha
            for rel, sha in blobs.items()
        )
        same_context = _declared_state_context(root, tip) == (
            "proposal" if proposal_head else "standalone"
        )
        same_proposal = _declared_proposal_head(root, tip) == proposal_head
        if same_ledger and same_context and same_proposal:
            return False

    listing = (f"100644 blob {blobs[FAILED]}\tfailed.json\n"
               f"100644 blob {blobs[QUEUE]}\tqueue.json\n").encode()
    tasks_tree = _git(root, ["mktree"], input_bytes=listing).stdout.decode().strip()
    root_tree = _git(root, ["mktree"],
                     input_bytes=f"040000 tree {tasks_tree}\ttasks\n".encode()).stdout.decode().strip()
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "hive-bot", "GIT_AUTHOR_EMAIL": "hive-bot@users.noreply.github.com",
           "GIT_COMMITTER_NAME": "hive-bot", "GIT_COMMITTER_EMAIL": "hive-bot@users.noreply.github.com"}
    commit_message = (
        f"{message}\n\n{TRAILER}: {digest}\n"
        f"{STATE_CONTEXT_TRAILER}: {'proposal' if proposal_head else 'standalone'}"
    )
    if proposal_head:
        commit_message += f"\n{PROPOSAL_HEAD_TRAILER}: {proposal_head}"
    args = ["commit-tree", root_tree, "-m", commit_message]
    if tip:
        args += ["-p", tip]
    if proposal_head and (not tip or not _is_ancestor(root, proposal_head, tip)):
        # Keep the referenced proposal commit reachable from hive/state so a
        # later run can compare ancestry even if it fetched only this branch.
        args += ["-p", proposal_head]
    commit = _git(root, args, env=env).stdout.decode().strip()
    _git(root, ["push", "origin", f"{commit}:refs/heads/{STATE_BRANCH}"])
    _git(root, ["update-ref", STATE_REF, commit])
    _ack(root, commit)
    return True
