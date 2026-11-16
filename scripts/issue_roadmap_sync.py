"""Pure, proposal-only roadmap reconciliation using verified GitHub evidence.

This module never writes roadmap state or GitHub. Inputs must be projected from
GitHub issue snapshots, cross-reference timeline events, PR metadata, and
check-runs. Issue bodies and comments are deliberately not accepted.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


class RoadmapReconciliationError(ValueError):
    """Raised when roadmap or GitHub evidence is malformed or ambiguous."""


_TASK_KEY = re.compile(r"[a-z0-9][a-z0-9-]{1,63}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ALLOWED_STATUSES = {"proposed", "approved", "blocked", "in_progress", "done", "needs-owner-triage"}
_DEFAULT_REQUIRED_CHECKS = ("audit", "validate")


def _aware_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RoadmapReconciliationError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RoadmapReconciliationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RoadmapReconciliationError(f"{field} must include a timezone")
    return parsed


def validate_task_graph(tasks: Any) -> dict[str, dict[str, Any]]:
    """Validate stable task identities, dependency references, and acyclicity."""
    if not isinstance(tasks, list):
        raise RoadmapReconciliationError("roadmap tasks must be a list")

    indexed: dict[str, dict[str, Any]] = {}
    issue_numbers: set[int] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise RoadmapReconciliationError("roadmap task must be an object")
        key = task.get("task_key")
        if not isinstance(key, str) or _TASK_KEY.fullmatch(key) is None:
            raise RoadmapReconciliationError("task_key must be a stable lowercase slug")
        if key in indexed:
            raise RoadmapReconciliationError(f"duplicate task_key: {key}")

        issue_number = task.get("issue_number")
        if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number < 1:
            raise RoadmapReconciliationError(f"{key}: issue_number must be a positive integer")
        if issue_number in issue_numbers:
            raise RoadmapReconciliationError(f"duplicate issue_number: {issue_number}")
        issue_numbers.add(issue_number)

        status = task.get("status")
        if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
            raise RoadmapReconciliationError(f"{key}: unsupported roadmap status")
        dependencies = task.get("dependencies", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) or _TASK_KEY.fullmatch(item) is None
            for item in dependencies
        ):
            raise RoadmapReconciliationError(f"{key}: dependencies must be task-key strings")
        if len(set(dependencies)) != len(dependencies):
            raise RoadmapReconciliationError(f"{key}: duplicate dependency")
        if key in dependencies:
            raise RoadmapReconciliationError(f"{key}: task cannot depend on itself")
        source_updated_at = task.get("source_updated_at")
        if source_updated_at is not None:
            _aware_timestamp(source_updated_at, f"{key}.source_updated_at")

        indexed[key] = {
            "task_key": key,
            "issue_number": issue_number,
            "status": status,
            "dependencies": list(dependencies),
            "source_updated_at": source_updated_at,
        }

    for key, task in indexed.items():
        for dependency in task["dependencies"]:
            if dependency not in indexed:
                raise RoadmapReconciliationError(
                    f"{key}: unknown dependency {dependency}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise RoadmapReconciliationError(f"dependency cycle includes {key}")
        if key in visited:
            return
        visiting.add(key)
        for dependency in indexed[key]["dependencies"]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in sorted(indexed):
        visit(key)
    return indexed


def _index_unique(records: Any, field: str, label: str) -> dict[int, dict[str, Any]]:
    if not isinstance(records, list):
        raise RoadmapReconciliationError(f"{label} must be a list")
    indexed: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise RoadmapReconciliationError(f"{label} entry must be an object")
        number = record.get(field)
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise RoadmapReconciliationError(f"{label} entry has an invalid {field}")
        if number in indexed:
            raise RoadmapReconciliationError(f"duplicate {label} record: {number}")
        indexed[number] = record
    return indexed


def _verified_pr_for_issue(issue_number: int, pull_requests: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = []
    for pr in pull_requests:
        if not isinstance(pr, dict):
            raise RoadmapReconciliationError("pull-request evidence entry must be an object")
        if pr.get("issue_number") != issue_number:
            continue
        # The collector must derive this marker from a GitHub cross-reference
        # timeline event, not from issue text, PR body text, or model output.
        if pr.get("link_evidence") != "github-cross-reference-event":
            continue
        matches.append(pr)
    if len(matches) > 1:
        raise RoadmapReconciliationError(
            f"issue #{issue_number} has multiple linked PR evidence records"
        )
    return matches[0] if matches else None


def _checks_pass_for_sha(
    checks: Any, sha: str, required_checks: tuple[str, ...]
) -> tuple[bool, list[str]]:
    if not isinstance(checks, list):
        raise RoadmapReconciliationError("check-runs must be a list")
    passed: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            raise RoadmapReconciliationError("check-run entry must be an object")
        check_sha = check.get("head_sha")
        name = check.get("name")
        conclusion = check.get("conclusion")
        if check_sha == sha and isinstance(name, str) and conclusion == "success":
            passed.add(name)
    missing = [name for name in required_checks if name not in passed]
    return not missing, missing


def build_reconciliation_proposal(
    roadmap_tasks: Any,
    issue_snapshots: Any,
    pull_request_evidence: Any,
    check_runs: Any,
    *,
    approved_task_keys: set[str] | None = None,
    required_checks: tuple[str, ...] = _DEFAULT_REQUIRED_CHECKS,
) -> dict[str, Any]:
    """Build a deterministic reconciliation proposal without applying changes.

    A task becomes eligible for a status proposal only when its issue and PR
    evidence are unambiguous, required checks passed on the exact PR head SHA,
    all dependencies are done, and its task key is explicitly owner-approved.
    """
    tasks = validate_task_graph(roadmap_tasks)
    issues = _index_unique(issue_snapshots, "number", "issue snapshot")
    if not isinstance(pull_request_evidence, list):
        raise RoadmapReconciliationError("pull-request evidence must be a list")
    if not isinstance(required_checks, tuple) or not required_checks or any(
        not isinstance(name, str) or not name for name in required_checks
    ):
        raise RoadmapReconciliationError("required_checks must be a non-empty tuple of names")
    approved = set() if approved_task_keys is None else approved_task_keys
    if not isinstance(approved, set) or any(
        not isinstance(key, str) or key not in tasks for key in approved
    ):
        raise RoadmapReconciliationError("approved_task_keys must contain known task keys")

    proposals: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    for key in sorted(tasks):
        task = tasks[key]
        issue = issues.get(task["issue_number"])
        if issue is None:
            unchanged.append({
                "task_key": key,
                "status": task["status"],
                "reason": "issue snapshot missing; no status inferred",
                "stale": True,
            })
            continue
        if not isinstance(issue.get("state"), str) or issue.get("state") not in {"open", "closed"}:
            raise RoadmapReconciliationError(
                f"{key}: issue state must be open or closed"
            )
        updated_at = _aware_timestamp(issue.get("updated_at"), f"issue #{task['issue_number']}.updated_at")
        source_updated_at = task["source_updated_at"]
        stale = source_updated_at is None or updated_at != _aware_timestamp(
            source_updated_at, f"{key}.source_updated_at"
        )

        pr = _verified_pr_for_issue(task["issue_number"], pull_request_evidence)
        desired_status = None
        evidence: dict[str, Any] = {
            "issue_number": task["issue_number"],
            "issue_state": issue["state"],
            "issue_updated_at": issue["updated_at"],
            "linked_pr_number": None,
            "head_sha": None,
            "required_checks": list(required_checks),
            "checks_passed": False,
        }
        reason = "insufficient verified PR/CI evidence; preserve current status"
        if pr is not None:
            pr_number = pr.get("number")
            head_sha = pr.get("head_sha")
            evidence["linked_pr_number"] = pr_number
            evidence["head_sha"] = head_sha
            if (
                isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number < 1
                or not isinstance(pr.get("state"), str) or pr.get("state") not in {"open", "closed"}
                or not isinstance(head_sha, str) or _SHA.fullmatch(head_sha) is None
            ):
                raise RoadmapReconciliationError(f"{key}: malformed linked PR evidence")
            if type(pr.get("merged")) is not bool:
                raise RoadmapReconciliationError(f"{key}: PR merged marker must be boolean")
            merged = pr["merged"]
            if merged and pr["state"] != "closed":
                raise RoadmapReconciliationError(f"{key}: merged PR must be closed")
            if merged:
                merge_sha = pr.get("merge_commit_sha")
                if not isinstance(merge_sha, str) or _SHA.fullmatch(merge_sha) is None:
                    raise RoadmapReconciliationError(f"{key}: merged PR lacks merge commit SHA")
                passed, missing = _checks_pass_for_sha(check_runs, head_sha, required_checks)
                evidence["checks_passed"] = passed
                evidence["missing_checks"] = missing
                if issue["state"] == "closed" and passed:
                    desired_status = "done"
                    reason = "issue closed; linked PR merged; required checks passed on exact PR head"
                elif issue["state"] == "open" and passed:
                    desired_status = "needs-owner-triage"
                    reason = "linked PR merged but issue remains open"
                else:
                    reason = "merged PR lacks exact-head required CI evidence or issue closure"
            elif pr["state"] == "open" and issue["state"] == "open":
                desired_status = "in_progress"
                reason = "open issue has a GitHub cross-referenced open PR"
            elif pr["state"] == "open":
                desired_status = "needs-owner-triage"
                reason = "issue is closed but its linked PR remains open"
        if desired_status is None or desired_status == task["status"]:
            unchanged.append({
                "task_key": key,
                "status": task["status"],
                "reason": reason,
                "stale": stale,
                "evidence": evidence,
            })
            continue

        dependencies_ready = all(tasks[dep]["status"] == "done" for dep in task["dependencies"])
        if not dependencies_ready:
            unchanged.append({
                "task_key": key,
                "status": task["status"],
                "reason": "dependency blocked: one or more prerequisites are not done",
                "stale": stale,
                "blocked_by": [
                    dep for dep in task["dependencies"] if tasks[dep]["status"] != "done"
                ],
                "evidence": evidence,
            })
            continue
        if stale:
            unchanged.append({
                "task_key": key,
                "status": task["status"],
                "reason": "roadmap source snapshot is stale; refresh before proposing a status change",
                "stale": True,
                "evidence": evidence,
            })
            continue
        if key not in approved:
            unchanged.append({
                "task_key": key,
                "status": task["status"],
                "reason": "status change requires explicit owner approval",
                "stale": False,
                "proposed_status": desired_status,
                "requires_owner_approval": True,
                "evidence": evidence,
            })
            continue
        proposals.append({
            "task_key": key,
            "issue_number": task["issue_number"],
            "from_status": task["status"],
            "to_status": desired_status,
            "requires_owner_approval": False,
            "evidence": evidence,
        })

    return {
        "schema_version": 1,
        "mode": "proposal-only",
        "roadmap_modified": False,
        "github_modified": False,
        "task_dispatch_performed": False,
        "proposals": proposals,
        "unchanged": unchanged,
    }
