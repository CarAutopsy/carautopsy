"""Select a trusted Hive ledger snapshot for the read-only owner digest.

This workflow helper may fetch origin/hive/state, but it never mutates Git refs,
the working tree, Hive state, or the repository. The digest renderer itself
remains offline and receives only the verified files copied into a temp folder.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys


STATE_REF = "refs/remotes/origin/hive/state"
STATE_BRANCH = "refs/heads/hive/state"
DIGEST_TRAILER = "Hive-Ledger-SHA256"


class SnapshotError(RuntimeError):
    """Raised when a trusted Hive snapshot cannot be selected."""


def _git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            input=input_bytes,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SnapshotError("Git snapshot operation failed") from exc
    return result.stdout


def final_trailer(root: Path, message: bytes, key: str) -> str | None:
    """Read a value only from Git's parsed final trailer block."""
    parsed = _git(root, "interpret-trailers", "--parse", input_bytes=message).decode("utf-8")
    prefix = key + ":"
    values = [
        line[len(prefix):].strip()
        for line in parsed.splitlines()
        if line.startswith(prefix)
    ]
    return values[0] if len(values) == 1 else None


def select_snapshot(root: Path) -> tuple[bytes, bytes, str, str]:
    """Return queue bytes, failed bytes, source label and integrity label."""
    root = Path(root).resolve()
    try:
        remote = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", "origin", STATE_BRANCH],
            cwd=root,
            capture_output=True,
        )
    except OSError as exc:
        raise SnapshotError("Could not query origin for the Hive state branch") from exc
    if remote.returncode == 0:
        _git(
            root,
            "fetch",
            "--no-tags",
            "origin",
            f"{STATE_BRANCH}:{STATE_REF}",
        )
        queue = _git(root, "show", f"{STATE_REF}:tasks/queue.json")
        failed = _git(root, "show", f"{STATE_REF}:tasks/failed.json")
        message = _git(root, "show", "-s", "--format=%B", STATE_REF)
        declared = final_trailer(root, message, DIGEST_TRAILER)
        actual = hashlib.sha256(failed + b"\0" + queue).hexdigest()
        if declared != actual:
            raise SnapshotError(
                "Hive state final ledger trailer is missing, duplicated, or mismatched; "
                "refusing an unverified report"
            )
        return queue, failed, "origin/hive/state", "verified-ledger-sha256"

    if remote.returncode == 2:
        try:
            queue = (root / "tasks" / "queue.json").read_bytes()
            failed = (root / "tasks" / "failed.json").read_bytes()
        except OSError as exc:
            raise SnapshotError("Main checkout Hive ledger is unavailable") from exc
        return queue, failed, "main-working-tree", "hive-state-branch-absent"

    raise SnapshotError(
        "Could not determine whether origin/hive/state exists; refusing to silently fall back"
    )


def prepare_snapshot(root: Path, output: Path) -> tuple[str, str]:
    queue, failed, source, integrity = select_snapshot(root)
    tasks = Path(output).resolve() / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / "queue.json").write_bytes(queue)
    (tasks / "failed.json").write_bytes(failed)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as stream:
            stream.write(f"root={tasks.parent}\n")
            stream.write(f"source={source}\n")
            stream.write(f"integrity={integrity}\n")
    return source, integrity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source, integrity = prepare_snapshot(args.repo_root, args.output)
    except SnapshotError as exc:
        print(f"Hive owner digest snapshot refused: {exc}", file=sys.stderr)
        return 2
    print(f"Hive snapshot prepared: source={source}; integrity={integrity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
