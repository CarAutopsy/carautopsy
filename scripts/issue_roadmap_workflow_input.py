"""Build a bounded live-evidence input from the canonical issue-roadmap snapshot.

This adapter is read-only. It selects only explicitly mapped roadmap issues from
the all-state crawler report; issue text and untracked issues never enter the
reconciliation evidence collector.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from issue_roadmap_sync import RoadmapReconciliationError, validate_task_graph


class WorkflowInputError(ValueError):
    """Raised when canonical roadmap or crawler input is unsafe."""


def _read_json(path: str) -> Any:
    try:
        return json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                WorkflowInputError("JSON contains a non-finite number")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise WorkflowInputError(f"could not read JSON input ({type(exc).__name__})") from exc


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def build_evidence_input(crawler: Any, roadmap: Any, *, repository: str) -> dict[str, Any]:
    if not isinstance(repository, str) or re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ) is None:
        raise WorkflowInputError("repository must use owner/name form")
    if not isinstance(crawler, dict) or (
        crawler.get("schema_version") != 1
        or crawler.get("mode") != "dry-run"
        or crawler.get("repository") != repository
        or crawler.get("roadmap_modified") is not False
        or crawler.get("github_modified") is not False
        or crawler.get("task_dispatch_performed") is not False
        or not isinstance(crawler.get("issue_snapshots"), list)
    ):
        raise WorkflowInputError("crawler report is not a matching read-only all-state snapshot")
    if not isinstance(roadmap, dict) or set(roadmap) != {
        "schema_version", "repository", "tasks"
    }:
        raise WorkflowInputError("canonical roadmap snapshot has an invalid shape")
    if (
        type(roadmap.get("schema_version")) is not int
        or roadmap["schema_version"] != 1
        or roadmap.get("repository") != repository
        or not isinstance(roadmap.get("tasks"), list)
    ):
        raise WorkflowInputError("canonical roadmap snapshot identity or schema is invalid")

    tasks = roadmap["tasks"]
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {
            "task_key", "issue_number", "status", "dependencies", "source_updated_at"
        }:
            raise WorkflowInputError("roadmap task must contain only the canonical reconciliation fields")
        if not _valid_timestamp(task.get("source_updated_at")):
            raise WorkflowInputError("every mapped task needs a timezone-aware source_updated_at")
    try:
        validate_task_graph(tasks)
    except RoadmapReconciliationError as exc:
        raise WorkflowInputError(f"canonical roadmap task graph is invalid: {exc}") from exc

    mapped_numbers = {task["issue_number"] for task in tasks}
    snapshots: dict[int, dict[str, Any]] = {}
    for item in crawler["issue_snapshots"]:
        if not isinstance(item, dict) or set(item) - {"number", "state", "updated_at"}:
            raise WorkflowInputError("crawler issue snapshot contains unsupported fields")
        number = item.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise WorkflowInputError("crawler issue snapshot has an invalid issue number")
        if number not in mapped_numbers:
            continue
        if number in snapshots:
            raise WorkflowInputError("duplicate mapped issue snapshots are ambiguous")
        if item.get("state") not in {"open", "closed"} or not _valid_timestamp(item.get("updated_at")):
            raise WorkflowInputError("mapped issue snapshot lacks valid state or timestamp")
        snapshots[number] = {
            "number": number,
            "state": item["state"],
            "updated_at": item["updated_at"],
        }

    return {
        "repository": repository,
        "roadmap_tasks": tasks,
        "issue_snapshots": [snapshots[number] for number in sorted(snapshots)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare read-only issue-roadmap evidence input from canonical snapshots."
    )
    parser.add_argument("--crawler-report", required=True)
    parser.add_argument("--roadmap-state", required=True)
    parser.add_argument("--repo", default="CarAutopsy/carautopsy")
    args = parser.parse_args(argv)
    try:
        result = build_evidence_input(
            _read_json(args.crawler_report),
            _read_json(args.roadmap_state),
            repository=args.repo,
        )
        sys.stdout.write(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
        return 0
    except WorkflowInputError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
