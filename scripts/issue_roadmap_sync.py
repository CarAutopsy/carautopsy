"""Pure, proposal-only roadmap reconciliation using verified GitHub evidence.

This module never writes roadmap state or GitHub. Inputs must be projected from
GitHub issue snapshots, cross-reference timeline events, PR metadata, and
check-runs. Issue bodies and comments are deliberately not accepted.
"""

from __future__ import annotations

import heapq
import re
from datetime import datetime
from typing import Any


class RoadmapReconciliationError(ValueError):
    """Raised when roadmap or GitHub evidence is malformed or ambiguous."""


_TASK_KEY = re.compile(r"[a-z0-9][a-z0-9-]{1,63}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_CHECK_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/runs/([1-9][0-9]*)\Z")
_ALLOWED_STATUSES = {"proposed", "approved", "blocked", "in_progress", "done", "needs-owner-triage"}
_MANDATORY_REQUIRED_CHECKS = ("audit", "validate")
_MAX_ROADMAP_TASKS = 5000
_MAX_DEPENDENCIES_PER_TASK = 100


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
    if len(tasks) > _MAX_ROADMAP_TASKS:
        raise RoadmapReconciliationError("roadmap task count exceeds the safety limit")

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
        if len(dependencies) > _MAX_DEPENDENCIES_PER_TASK:
            raise RoadmapReconciliationError(f"{key}: dependency count exceeds the safety limit")
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

    # Iterative Kahn traversal avoids recursion-depth failures on long or
    # adversarial dependency chains.
    indegree = {key: len(task["dependencies"]) for key, task in indexed.items()}
    dependents = {key: [] for key in indexed}
    for key, task in indexed.items():
        for dependency in task["dependencies"]:
            dependents[dependency].append(key)

    ready = [key for key, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    visited_count = 0
    while ready:
        key = heapq.heappop(ready)
        visited_count += 1
        for dependent in dependents[key]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)

    if visited_count != len(indexed):
        cycle_keys = sorted(key for key, degree in indegree.items() if degree > 0)
        raise RoadmapReconciliationError(
            "dependency cycle includes " + ", ".join(cycle_keys[:5])
        )
    return indexed


def _index_unique(records: Any, field: str, label: str) -> tuple[dict[int, dict[str, Any]], set[int]]:
    if not isinstance(records, list):
        raise RoadmapReconciliationError(f"{label} must be a list")
    indexed: dict[int, dict[str, Any]] = {}
    ambiguous: set[int] = set()
    for record in records:
        if not isinstance(record, dict):
            raise RoadmapReconciliationError(f"{label} entry must be an object")
        number = record.get(field)
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise RoadmapReconciliationError(f"{label} entry has an invalid {field}")
        if number in ambiguous:
            continue
        if number in indexed:
            del indexed[number]
            ambiguous.add(number)
            continue
        indexed[number] = record
    return indexed, ambiguous


def _index_linked_prs(records: Any) -> tuple[dict[int, dict[str, Any]], set[int]]:
    if not isinstance(records, list) or len(records) > 20_000:
        raise RoadmapReconciliationError("pull-request evidence must be a bounded list")
    by_issue: dict[int, list[dict[str, Any]]] = {}
    metadata_by_pr: dict[int, tuple[str, bool, str, str | None]] = {}
    issues_by_pr: dict[int, set[int]] = {}
    conflicting_pr_numbers: set[int] = set()

    for pr in records:
        if not isinstance(pr, dict):
            raise RoadmapReconciliationError("pull-request evidence entry must be an object")
        # Unverified associations are ignored; they cannot poison verified records.
        if pr.get("link_evidence") != "github-cross-reference-event":
            continue
        issue_number = pr.get("issue_number")
        pr_number = pr.get("number")
        if (
            isinstance(issue_number, bool)
            or not isinstance(issue_number, int)
            or issue_number < 1
            or isinstance(pr_number, bool)
            or not isinstance(pr_number, int)
            or pr_number < 1
        ):
            raise RoadmapReconciliationError("linked PR has an invalid issue_number or PR number")

        state = pr.get("state")
        merged = pr.get("merged")
        head_sha = pr.get("head_sha")
        merge_sha = pr.get("merge_commit_sha")
        if type(merged) is not bool:
            raise RoadmapReconciliationError("PR merged marker must be boolean")
        if (
            not isinstance(state, str) or state not in {"open", "closed"}
            or not isinstance(head_sha, str) or _SHA.fullmatch(head_sha) is None
            or (merge_sha is not None and (
                not isinstance(merge_sha, str) or _SHA.fullmatch(merge_sha) is None
            ))
            or (merged and (state != "closed" or merge_sha is None))
        ):
            raise RoadmapReconciliationError("linked PR metadata is malformed")

        metadata = (state, merged, head_sha, merge_sha)
        previous = metadata_by_pr.get(pr_number)
        if previous is not None and previous != metadata:
            conflicting_pr_numbers.add(pr_number)
        else:
            metadata_by_pr[pr_number] = metadata
        issues_by_pr.setdefault(pr_number, set()).add(issue_number)
        by_issue.setdefault(issue_number, []).append(pr)

    ambiguous = {number for number, matches in by_issue.items() if len(matches) > 1}
    for pr_number in conflicting_pr_numbers:
        ambiguous.update(issues_by_pr[pr_number])
    return {
        number: matches[0] for number, matches in by_issue.items() if number not in ambiguous
    }, ambiguous


def _index_check_runs(checks: Any, required_checks: tuple[str, ...]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    if not isinstance(checks, list) or len(checks) > 100_000:
        raise RoadmapReconciliationError("check-runs must be a bounded list")
    by_sha: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for check in checks:
        if not isinstance(check, dict):
            raise RoadmapReconciliationError("check-run entry must be an object")
        sha = check.get("head_sha")
        name = check.get("name")
        if isinstance(sha, str) and _SHA.fullmatch(sha) and isinstance(name, str) and name in required_checks:
            by_sha.setdefault(sha, {}).setdefault(name, []).append({
                "id": check.get("id"),
                "name": name,
                "head_sha": sha,
                "conclusion": check.get("conclusion"),
                "html_url": check.get("html_url"),
            })
    return by_sha


def _checks_pass_for_sha(
    checks_by_sha: dict[str, dict[str, list[dict[str, Any]]]],
    sha: str,
    required_checks: tuple[str, ...],
    repository: str,
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    observed = checks_by_sha.get(sha, {})
    missing: list[str] = []
    evidence: list[dict[str, Any]] = []
    for name in required_checks:
        matches = observed.get(name, [])
        if len(matches) != 1:
            missing.append(name)
            continue
        check = matches[0]
        check_id = check.get('id')
        html_url = check.get('html_url')
        url_match = _CHECK_URL.fullmatch(html_url) if isinstance(html_url, str) and len(html_url) <= 300 else None
        if (
            check.get('conclusion') != 'success'
            or isinstance(check_id, bool) or not isinstance(check_id, int) or check_id < 1
            or url_match is None
            or url_match.group(1) != repository
            or url_match.group(2) != str(check_id)
        ):
            missing.append(name)
            continue
        evidence.append(check)
    id_names: dict[int, list[str]] = {}
    url_names: dict[str, list[str]] = {}
    for item in evidence:
        id_names.setdefault(item['id'], []).append(item['name'])
        url_names.setdefault(item['html_url'], []).append(item['name'])
    ambiguous_names = {name for group in list(id_names.values()) + list(url_names.values()) if len(group) > 1 for name in group}
    if ambiguous_names:
        missing = sorted(set(missing).union(ambiguous_names))
        evidence = [item for item in evidence if item['name'] not in ambiguous_names]
    return not missing, missing, evidence

def build_reconciliation_proposal(
    roadmap_tasks: Any,
    issue_snapshots: Any,
    pull_request_evidence: Any,
    check_runs: Any,
    *,
    approved_task_keys: set[str] | None = None,
    required_checks: tuple[str, ...] = (),
    repository: str = 'CarAutopsy/carautopsy',
) -> dict[str, Any]:
    """Build a deterministic reconciliation proposal without applying changes.

    A task becomes eligible for a status proposal only when its issue and PR
    evidence are unambiguous, required checks passed on the exact PR head SHA,
    all dependencies are done, and its task key is explicitly owner-approved.
    """
    if not isinstance(repository, str) or re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) is None:
        raise RoadmapReconciliationError('repository must be owner/name')
    tasks = validate_task_graph(roadmap_tasks)
    issues, ambiguous_issue_snapshots = _index_unique(issue_snapshots, "number", "issue snapshot")
    if not isinstance(required_checks, tuple) or any(
        not isinstance(name, str) or not name for name in required_checks
    ):
        raise RoadmapReconciliationError("additional required checks must be a tuple of names")
    effective_required_checks = tuple(dict.fromkeys((*_MANDATORY_REQUIRED_CHECKS, *required_checks)))
    linked_prs, ambiguous_linked_prs = _index_linked_prs(pull_request_evidence)
    checks_by_sha = _index_check_runs(check_runs, effective_required_checks)
    approved = set() if approved_task_keys is None else approved_task_keys
    if not isinstance(approved, set) or any(
        not isinstance(key, str) or key not in tasks for key in approved
    ):
        raise RoadmapReconciliationError("approved_task_keys must contain known task keys")

    proposals: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    for key in sorted(tasks):
        task = tasks[key]
        issue_number = task["issue_number"]
        if issue_number in ambiguous_issue_snapshots:
            unchanged.append({
                "task_key": key,
                "status": task["status"],
                "reason": "duplicate issue snapshots; no status inferred",
                "stale": True,
            })
            continue
        issue = issues.get(issue_number)
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

        if issue_number in ambiguous_linked_prs:
            unchanged.append({
                "task_key": key,
                "status": task["status"],
                "reason": "ambiguous or conflicting linked PR records; no status inferred",
                "stale": stale,
                "evidence": {
                    "issue_number": issue_number,
                    "issue_state": issue["state"],
                    "issue_updated_at": issue["updated_at"],
                    "linked_pr_number": None,
                    "head_sha": None,
                    "required_checks": list(effective_required_checks),
                    "checks_passed": False,
                    "check_evidence": [],
                },
            })
            continue

        pr = linked_prs.get(issue_number)
        desired_status = None
        evidence: dict[str, Any] = {
            "issue_number": issue_number,
            "issue_state": issue["state"],
            "issue_updated_at": issue["updated_at"],
            "linked_pr_number": None,
            "head_sha": None,
            "required_checks": list(effective_required_checks),
            "checks_passed": False,
            "check_evidence": [],
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
                evidence["merge_commit_sha"] = merge_sha
                passed, missing, check_evidence = _checks_pass_for_sha(checks_by_sha, head_sha, effective_required_checks, repository)
                evidence["checks_passed"] = passed
                evidence["missing_checks"] = missing
                evidence["check_evidence"] = check_evidence
                if issue["state"] == "open":
                    desired_status = "needs-owner-triage"
                    reason = "linked PR merged but issue remains open"
                elif passed:
                    desired_status = "done"
                    reason = "issue closed; linked PR merged; required checks passed on exact PR head"
                else:
                    reason = "closed issue and merged PR lack exact-head required CI evidence"
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
