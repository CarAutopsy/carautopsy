"""Owner-approved, proposal-bound roadmap apply planning.

This module validates a separate owner approval manifest and returns a
deterministic Markdown update plan. It never writes files or calls GitHub.
The workflow that eventually commits a plan must enforce owner identity and
optimistic-concurrency SHA independently.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime
from typing import Any

from issue_roadmap_sync import RoadmapReconciliationError, validate_task_graph


class RoadmapApplyError(ValueError):
    """Raised when an owner-approved roadmap apply request is unsafe."""


_TASK_KEY = re.compile(r"[a-z0-9][a-z0-9-]{1,63}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
_CONFIRMATION = "APPLY ROADMAP PROPOSAL"
_START = "<!-- carautopsy-issue-roadmap:start -->"
_DATA_START = "<!-- carautopsy-issue-roadmap:data:start -->"
_DATA_END = "<!-- carautopsy-issue-roadmap:data:end -->"
_END = "<!-- carautopsy-issue-roadmap:end -->"
_MAX_ROADMAP_BYTES = 500_000
_MAX_REPORT_BYTES = 5_000_000
_MAX_REPORT_ITEMS = 100_000
_MAX_APPROVED_TASKS = 100
_MAX_CRITERIA = 20
_MAX_TEXT = 500


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _canonical_json(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > _MAX_REPORT_BYTES:
            raise RoadmapApplyError("proposal report exceeds the size limit")
        return encoded
    except (TypeError, ValueError, RecursionError) as exc:
        raise RoadmapApplyError("proposal report is not safe JSON") from exc


def proposal_digest(report: Any) -> str:
    """Return the stable identity of the exact dry-run report."""
    if not isinstance(report, dict):
        raise RoadmapApplyError("proposal report must be an object")
    return "sha256:" + hashlib.sha256(_canonical_json(report)).hexdigest()


def _plain_text(value: Any, field: str, *, maximum: int = _MAX_TEXT) -> str:
    if (
        not isinstance(value, str) or not value.strip() or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise RoadmapApplyError(f"{field} must be bounded plain text")
    return value.strip()


def _validate_report(report: Any, repository: str) -> tuple[str, dict[int, dict[str, Any]]]:
    allowed_report_fields = {
        "schema_version", "mode", "repository", "source", "issue_snapshots_seen",
        "api_records_seen", "pull_request_snapshots_excluded", "issue_snapshots",
        "snapshot_classification_counts", "proposal_count", "actionable_proposal_count",
        "owner_triage_count", "requires_owner_approval", "roadmap_modified",
        "github_modified", "task_dispatch_performed", "proposals",
    }
    if not isinstance(report, dict) or set(report) - allowed_report_fields or (
        type(report.get("schema_version")) is not int or report.get("schema_version") != 1
        or report.get("mode") != "dry-run"
        or report.get("repository") != repository
        or report.get("source") != "github-all-issues"
        or report.get("requires_owner_approval") is not True
        or report.get("roadmap_modified") is not False
        or report.get("github_modified") is not False
        or report.get("task_dispatch_performed") is not False
        or not isinstance(report.get("proposals"), list)
        or len(report.get("proposals", [])) > _MAX_REPORT_ITEMS
        or not isinstance(report.get("issue_snapshots"), list)
        or len(report.get("issue_snapshots", [])) > _MAX_REPORT_ITEMS
    ):
        raise RoadmapApplyError("only a bounded read-only all-state crawler report can be approved")

    snapshots: dict[int, dict[str, Any]] = {}
    duplicate_numbers: set[int] = set()
    for item in report["issue_snapshots"]:
        if not isinstance(item, dict) or set(item) - {"number", "state", "updated_at"}:
            raise RoadmapApplyError("issue evidence has an invalid shape")
        number = item.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise RoadmapApplyError("issue evidence has an invalid issue number")
        if number in snapshots:
            duplicate_numbers.add(number)
            continue
        if item.get("state") not in {"open", "closed"} or not _aware_timestamp(item.get("updated_at")):
            raise RoadmapApplyError("issue evidence must include a valid state and timezone-aware updated_at")
        snapshots[number] = item
    if duplicate_numbers:
        raise RoadmapApplyError("duplicate issue snapshots make evidence ambiguous")
    return proposal_digest(report), snapshots


def _load_managed_state(markdown: str) -> tuple[dict[str, Any], str | None]:
    markers = (_START, _DATA_START, _DATA_END, _END)
    counts = [markdown.count(marker) for marker in markers]
    if counts == [0, 0, 0, 0]:
        return {"schema_version": 1, "applied_proposals": [], "tasks": []}, None
    if counts != [1, 1, 1, 1]:
        raise RoadmapApplyError("managed roadmap markers are incomplete or duplicated")

    start = markdown.index(_START)
    data_start = markdown.index(_DATA_START, start) + len(_DATA_START)
    data_end = markdown.index(_DATA_END, data_start)
    end = markdown.index(_END, data_end) + len(_END)
    if not (start < data_start < data_end < end):
        raise RoadmapApplyError("managed roadmap markers are out of order")
    block = markdown[start:end]
    try:
        state = json.loads(
            markdown[data_start:data_end].strip(),
            parse_constant=lambda value: (_ for _ in ()).throw(
                RoadmapApplyError("managed roadmap JSON contains a non-finite number")
            ),
        )
    except (ValueError, RecursionError) as exc:
        raise RoadmapApplyError("managed roadmap state is malformed") from exc
    if not isinstance(state, dict) or set(state) != {"schema_version", "applied_proposals", "tasks"}:
        raise RoadmapApplyError("managed roadmap state has an invalid shape")
    if type(state.get("schema_version")) is not int or state["schema_version"] != 1:
        raise RoadmapApplyError("unsupported managed roadmap schema")
    if (
        not isinstance(state.get("applied_proposals"), list)
        or any(not isinstance(item, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", item) for item in state["applied_proposals"])
        or len(set(state["applied_proposals"])) != len(state["applied_proposals"])
        or not isinstance(state.get("tasks"), list)
    ):
        raise RoadmapApplyError("managed roadmap state is malformed")
    if len(state["tasks"]) > 5000:
        raise RoadmapApplyError("managed roadmap task count exceeds the safety limit")
    task_fields = {
        "task_key", "issue_number", "title", "status", "dependencies",
        "acceptance_criteria", "source_updated_at",
    }
    for task in state["tasks"]:
        if not isinstance(task, dict) or set(task) != task_fields:
            raise RoadmapApplyError("managed roadmap task has an invalid shape")
        _plain_text(task.get("title"), "managed task title", maximum=200)
        criteria = task.get("acceptance_criteria")
        if not isinstance(criteria, list) or not 1 <= len(criteria) <= _MAX_CRITERIA:
            raise RoadmapApplyError("managed task acceptance criteria are malformed")
        for criterion in criteria:
            _plain_text(criterion, "managed acceptance criterion")
        if task.get("status") != "approved":
            raise RoadmapApplyError("managed issue intake tasks must remain proposed")
        if not isinstance(task.get("dependencies"), list):
            raise RoadmapApplyError("managed task dependencies are malformed")
        if not _aware_timestamp(task.get("source_updated_at")):
            raise RoadmapApplyError("managed task source timestamp is malformed")
    try:
        validate_task_graph([
            {
                "task_key": item["task_key"],
                "issue_number": item["issue_number"],
                "status": item["status"],
                "dependencies": item["dependencies"],
                "source_updated_at": item["source_updated_at"],
            }
            for item in state["tasks"]
        ])
    except (KeyError, RoadmapReconciliationError) as exc:
        raise RoadmapApplyError("managed roadmap dependency graph is invalid") from exc
    if _render_managed_block(state) != block:
        raise RoadmapApplyError("managed roadmap block was edited outside the apply controller")
    return state, block


def _escape_cell(value: str) -> str:
    return (
        html.escape(value, quote=True)
        .replace("|", "&#124;")
        .replace(chr(96), "&#96;")
        .replace("\\", "&#92;")
    )


def _render_managed_block(state: dict[str, Any]) -> str:
    canonical = json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).replace("--", "\\u002d\\u002d")
    lines = [
        _START,
        "## Owner-approved issue intake",
        "",
        "Entries below were added only from a proposal with an explicit owner approval record.",
        "",
        _DATA_START,
        canonical,
        _DATA_END,
        "",
        "| Task ID | Issue | Title | Status | Dependencies | Acceptance criteria | Source updated |",
        "|---|---:|---|---|---|---|---|",
    ]
    for task in sorted(state["tasks"], key=lambda item: item["task_key"]):
        dependencies = ", ".join(
            f"<code>{_escape_cell(item)}</code>" for item in task["dependencies"]
        ) or "—"
        criteria = "<br>".join(_escape_cell(item) for item in task["acceptance_criteria"])
        lines.append(
            f"| <code>{task['task_key']}</code> | #{task['issue_number']} | "
            f"{_escape_cell(task['title'])} | {task['status']} | "
            f"{dependencies} | {criteria} | {task['source_updated_at']} |"
        )
    lines.append(_END)
    return "\n".join(lines)


def build_owner_approved_apply_plan(
    report: Any,
    approval: Any,
    current_roadmap: str,
    current_roadmap_sha: str,
    *,
    repository: str,
    expected_owner_login: str,
) -> dict[str, Any]:
    """Build an idempotent, SHA-bound apply plan without writing any state."""
    if not isinstance(repository, str) or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise RoadmapApplyError("repository must be owner/name")
    if not isinstance(expected_owner_login, str) or _OWNER.fullmatch(expected_owner_login) is None:
        raise RoadmapApplyError("expected owner login is invalid")
    if not isinstance(current_roadmap, str) or len(current_roadmap.encode("utf-8")) > _MAX_ROADMAP_BYTES:
        raise RoadmapApplyError("current roadmap is missing or exceeds the size limit")
    if not isinstance(current_roadmap_sha, str) or _SHA.fullmatch(current_roadmap_sha) is None:
        raise RoadmapApplyError("current roadmap SHA is invalid")

    digest, snapshots = _validate_report(report, repository)
    required_approval_fields = {
        "schema_version", "repository", "owner_login", "proposal_id",
        "expected_roadmap_sha", "approved_at", "confirmation", "approved_tasks",
    }
    if not isinstance(approval, dict) or set(approval) != required_approval_fields:
        raise RoadmapApplyError("approval manifest has an invalid shape")
    if type(approval.get("schema_version")) is not int or approval["schema_version"] != 1:
        raise RoadmapApplyError("unsupported approval manifest schema")
    if approval.get("repository") != repository:
        raise RoadmapApplyError("approval repository does not match")
    if approval.get("owner_login") != expected_owner_login:
        raise RoadmapApplyError("approval must be issued by the configured repository owner")
    if approval.get("proposal_id") != digest:
        raise RoadmapApplyError("approval proposal ID does not match the exact crawler report")
    expected_sha = approval.get("expected_roadmap_sha")
    if not isinstance(expected_sha, str) or _SHA.fullmatch(expected_sha) is None:
        raise RoadmapApplyError("approval must pin the current roadmap blob SHA")
    if not _aware_timestamp(approval.get("approved_at")):
        raise RoadmapApplyError("approval timestamp must include a timezone")
    if approval.get("confirmation") != _CONFIRMATION:
        raise RoadmapApplyError("explicit apply confirmation phrase is required")
    approved = approval.get("approved_tasks")
    if not isinstance(approved, list) or not 1 <= len(approved) <= _MAX_APPROVED_TASKS:
        raise RoadmapApplyError("approval must contain a bounded non-empty task list")

    actionable: dict[str, dict[str, Any]] = {}
    for proposal in report["proposals"]:
        if not isinstance(proposal, dict):
            raise RoadmapApplyError("proposal entry must be an object")
        if proposal.get("classification") == "actionable":
            key = proposal.get("task_key")
            issue_number = proposal.get("issue_number")
            if (
                not isinstance(key, str) or _TASK_KEY.fullmatch(key) is None or key in actionable
                or isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number < 1
                or proposal.get("status") != "proposed"
                or proposal.get("owner_input_required") is not True
                or proposal.get("requires_owner_approval") is not True
                or not isinstance(proposal.get("title"), str)
            ):
                raise RoadmapApplyError("actionable proposal identities or owner gates are invalid")
            actionable[key] = proposal

    state, old_block = _load_managed_state(current_roadmap)
    existing_tasks = state["tasks"]
    try:
        validate_task_graph([
            {
                "task_key": item["task_key"],
                "issue_number": item["issue_number"],
                "status": item["status"],
                "dependencies": item["dependencies"],
                "source_updated_at": item["source_updated_at"],
            }
            for item in existing_tasks
        ])
    except (KeyError, RoadmapReconciliationError) as exc:
        raise RoadmapApplyError("existing managed roadmap tasks are invalid") from exc

    normalized: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in approved:
        fields = {"task_key", "issue_number", "title", "dependencies", "acceptance_criteria"}
        if not isinstance(item, dict) or set(item) != fields:
            raise RoadmapApplyError("approved task has an invalid shape")
        key = item.get("task_key")
        issue_number = item.get("issue_number")
        if (
            not isinstance(key, str) or _TASK_KEY.fullmatch(key) is None or key in seen_keys
            or isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number < 1
            or key != f"issue-{issue_number}"
        ):
            raise RoadmapApplyError("approved task key or issue number is invalid or duplicated")
        proposal = actionable.get(key)
        if proposal is None or proposal.get("issue_number") != issue_number:
            raise RoadmapApplyError("approved task is not an actionable proposal in this report")
        if proposal.get("title") != item.get("title"):
            raise RoadmapApplyError("approved task title does not match the crawler proposal")
        snapshot = snapshots.get(issue_number)
        if snapshot is None or snapshot["state"] != "open":
            raise RoadmapApplyError("only a uniquely evidenced open issue can be approved")
        dependencies = item.get("dependencies")
        if (
            not isinstance(dependencies, list) or len(dependencies) > 100
            or any(not isinstance(dep, str) or _TASK_KEY.fullmatch(dep) is None for dep in dependencies)
            or len(set(dependencies)) != len(dependencies) or key in dependencies
        ):
            raise RoadmapApplyError("dependencies must be unique valid task keys")
        criteria = item.get("acceptance_criteria")
        if not isinstance(criteria, list) or not 1 <= len(criteria) <= _MAX_CRITERIA:
            raise RoadmapApplyError("owner must supply one or more acceptance criteria")
        criteria = [_plain_text(value, "acceptance criterion") for value in criteria]
        normalized.append({
            "task_key": key,
            "issue_number": issue_number,
            "title": _plain_text(item["title"], "task title", maximum=200),
            "status": "approved",
            "dependencies": dependencies,
            "acceptance_criteria": criteria,
            "source_updated_at": snapshot["updated_at"],
        })
        seen_keys.add(key)

    existing_by_key = {item["task_key"]: item for item in existing_tasks}
    approved_by_key = {item["task_key"]: item for item in normalized}
    if digest in state["applied_proposals"]:
        if any(existing_by_key.get(key) != task for key, task in approved_by_key.items()):
            raise RoadmapApplyError("proposal ID was already applied with different task content")
        return {
            "schema_version": 1,
            "mode": "no-op-already-applied",
            "proposal_id": digest,
            "changed_task_keys": [],
            "already_applied_task_keys": sorted(approved_by_key),
            "roadmap_sha_before": current_roadmap_sha,
            "roadmap_sha256_after": hashlib.sha256(current_roadmap.encode("utf-8")).hexdigest(),
            "roadmap_content": current_roadmap,
            "roadmap_modified": False,
        }

    if expected_sha != current_roadmap_sha:
        raise RoadmapApplyError("roadmap changed since owner approval; regenerate and re-approve the proposal")

    changed: list[str] = []
    already: list[str] = []
    for key, task in approved_by_key.items():
        previous = existing_by_key.get(key)
        if previous is None:
            changed.append(key)
        elif previous == task:
            already.append(key)
        else:
            raise RoadmapApplyError("task key already exists with different content")

    all_tasks = list(existing_tasks)
    for key in changed:
        all_tasks.append(approved_by_key[key])
    allowed_keys = {item["task_key"] for item in all_tasks}
    if any(dep not in allowed_keys for item in all_tasks for dep in item["dependencies"]):
        raise RoadmapApplyError("dependency references an unknown task key")
    try:
        validate_task_graph([
            {
                "task_key": item["task_key"],
                "issue_number": item["issue_number"],
                "status": item["status"],
                "dependencies": item["dependencies"],
                "source_updated_at": item["source_updated_at"],
            }
            for item in all_tasks
        ])
    except RoadmapReconciliationError as exc:
        raise RoadmapApplyError("approved tasks create an invalid roadmap dependency graph") from exc

    next_state = {
        "schema_version": 1,
        "applied_proposals": sorted([*state["applied_proposals"], digest]),
        "tasks": sorted(all_tasks, key=lambda item: item["task_key"]),
    }
    block = _render_managed_block(next_state)
    if old_block is None:
        separator = "" if not current_roadmap else ("" if current_roadmap.endswith("\n\n") else "\n" if current_roadmap.endswith("\n") else "\n\n")
        updated = current_roadmap + separator + block + "\n"
    else:
        updated = current_roadmap.replace(old_block, block, 1)
    if len(updated.encode("utf-8")) > _MAX_ROADMAP_BYTES:
        raise RoadmapApplyError("updated roadmap exceeds the size limit")

    return {
        "schema_version": 1,
        "mode": "apply-plan",
        "proposal_id": digest,
        "changed_task_keys": sorted(changed),
        "already_applied_task_keys": sorted(already),
        "roadmap_sha_before": current_roadmap_sha,
        "roadmap_sha256_after": hashlib.sha256(updated.encode("utf-8")).hexdigest(),
        "roadmap_content": updated,
        "roadmap_modified": False,
    }
