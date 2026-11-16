"""Deterministic proposal artifact and comment renderer.

Rendering is side-effect free. It never posts comments or modifies roadmap state.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any


class ProposalArtifactError(ValueError):
    """Raised when a reconciliation report is not safe to render."""


_TASK_KEY = re.compile(r"[a-z0-9][a-z0-9-]{1,63}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_CHECK_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(?:actions/)?runs/([1-9][0-9]*)(?:/job/([1-9][0-9]*))?\Z")
_CHECK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.:/-]{0,99}\Z")
_STATUSES = {"proposed", "approved", "blocked", "in_progress", "done", "needs-owner-triage"}
_MAX_REPORT_ITEMS = 5000
_MAX_REPORT_BYTES = 5_000_000
_MAX_REASON_CHARS = 1000
_MAX_MARKDOWN_BYTES = 60_000


_REPORT_FIELDS = {
    "schema_version", "mode", "roadmap_modified", "github_modified",
    "task_dispatch_performed", "proposals", "unchanged", "repository",
    "source", "issue_snapshots_seen",
}
_EVIDENCE_FIELDS = {
    "issue_number", "issue_state", "issue_updated_at", "linked_pr_number",
    "head_sha", "required_checks", "checks_passed", "missing_checks",
    "merge_commit_sha", "check_evidence",
}


def _validate_check_record(check: Any, head_sha: str, repository: str) -> dict[str, Any]:
    if not isinstance(check, dict):
        raise ProposalArtifactError("CI check evidence entry must be an object")
    check_id = check.get("id")
    name = check.get("name")
    url = check.get("html_url")
    if (
        set(check) != {"id", "name", "head_sha", "conclusion", "html_url"}
        or isinstance(check_id, bool) or not isinstance(check_id, int) or check_id < 1
        or not isinstance(name, str) or _CHECK_NAME.fullmatch(name) is None
        or check.get("head_sha") != head_sha
        or check.get("conclusion") != "success"
        or not isinstance(url, str) or len(url) > 300
    ):
        raise ProposalArtifactError("CI check evidence is incomplete or mismatched")
    url_match = _CHECK_URL.fullmatch(url)
    linked_id = (url_match.group(3) or url_match.group(2)) if url_match else None
    if url_match is None or url_match.group(1) != repository or linked_id != str(check_id):
        raise ProposalArtifactError("CI check URL does not identify this repository and check-run ID")
    return check


def _validate_check_evidence(evidence: dict[str, Any], head_sha: str, repository: str) -> list[dict[str, Any]]:
    required = evidence.get("required_checks")
    checks = evidence.get("check_evidence")
    if (
        not isinstance(required, list)
        or len(required) > 10
        or any(not isinstance(name, str) or _CHECK_NAME.fullmatch(name) is None for name in required)
        or len(set(required)) != len(required)
        or not {"audit", "validate"}.issubset(set(required))
        or not isinstance(checks, list)
        or len(checks) > 10
    ):
        raise ProposalArtifactError("done proposal lacks required CI check evidence")

    indexed: dict[str, dict[str, Any]] = {}
    ids: set[int] = set()
    urls: set[str] = set()
    for raw_check in checks:
        check = _validate_check_record(raw_check, head_sha, repository)
        name = check["name"]
        if name not in required or name in indexed or check["id"] in ids or check["html_url"] in urls:
            raise ProposalArtifactError("CI check evidence contains duplicate or unexpected references")
        indexed[name] = check
        ids.add(check["id"])
        urls.add(check["html_url"])
    if set(indexed) != set(required):
        raise ProposalArtifactError("done proposal lacks audit/validate check-run references")
    return [indexed[name] for name in required]


def _render_check_links(evidence: dict[str, Any], repository: str, *, require_complete: bool) -> str:
    head_sha = evidence.get("head_sha")
    if require_complete:
        checks = _validate_check_evidence(evidence, head_sha, repository)
    else:
        raw_checks = evidence.get("check_evidence", [])
        if not isinstance(raw_checks, list) or len(raw_checks) > 10:
            return "CI evidence unavailable"
        try:
            checks = [_validate_check_record(item, head_sha, repository) for item in raw_checks]
        except ProposalArtifactError:
            return "CI evidence unavailable"
    if not checks:
        missing = evidence.get("missing_checks", [])
        if isinstance(missing, list) and missing:
            return "missing: " + ", ".join(html.escape(str(name)) for name in missing)
        return "CI evidence pending"
    return ", ".join(
        f"[{html.escape(check['name'])}]({check['html_url']})" for check in checks
    )


def _validate_evidence(
    evidence: Any, issue_number: int, repository: str, *,
    require_done: bool = False, allow_missing_pr: bool = False,
) -> dict[str, Any]:
    if not isinstance(evidence, dict) or set(evidence) - _EVIDENCE_FIELDS:
        raise ProposalArtifactError("proposal evidence has an invalid shape")
    evidence_issue = evidence.get("issue_number")
    linked_pr = evidence.get("linked_pr_number")
    head_sha = evidence.get("head_sha")
    issue_state = evidence.get("issue_state")
    updated_at = evidence.get("issue_updated_at")
    required = evidence.get("required_checks")
    checks = evidence.get("check_evidence", [])
    missing = evidence.get("missing_checks", [])
    merge_sha = evidence.get("merge_commit_sha")
    if (
        isinstance(evidence_issue, bool) or not isinstance(evidence_issue, int) or evidence_issue != issue_number
        or not (allow_missing_pr and linked_pr is None and head_sha is None) and (
            isinstance(linked_pr, bool) or not isinstance(linked_pr, int) or linked_pr < 1
            or not isinstance(head_sha, str) or _SHA.fullmatch(head_sha) is None
        )
        or not isinstance(issue_state, str) or issue_state not in {"open", "closed"}
        or not isinstance(updated_at, str) or len(updated_at) > 64
        or not isinstance(required, list) or len(required) > 10
        or any(not isinstance(name, str) or _CHECK_NAME.fullmatch(name) is None for name in required)
        or len(set(required)) != len(required)
        or not {"audit", "validate"}.issubset(set(required))
        or type(evidence.get("checks_passed")) is not bool
        or not isinstance(checks, list) or len(checks) > 10
        or not isinstance(missing, list) or len(missing) > 10
        or any(not isinstance(name, str) or name not in required for name in missing)
        or (merge_sha is not None and (not isinstance(merge_sha, str) or _SHA.fullmatch(merge_sha) is None))
    ):
        raise ProposalArtifactError("proposal evidence is incomplete or malformed")
    if linked_pr is None and (checks or merge_sha is not None or evidence["checks_passed"]):
        raise ProposalArtifactError("PR-less evidence cannot claim CI or merge success")
    if require_done:
        if linked_pr is None or merge_sha is None or evidence["checks_passed"] is not True or missing:
            raise ProposalArtifactError("done proposal lacks a valid merge commit SHA or CI evidence")
        _validate_check_evidence(evidence, head_sha, repository)
    elif linked_pr is not None:
        for check in checks:
            _validate_check_record(check, head_sha, repository)
    elif checks:
        raise ProposalArtifactError("PR-less evidence cannot contain CI check records")
    return evidence


def _validate_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or set(report) - _REPORT_FIELDS:
        raise ProposalArtifactError("reconciliation report must be a known-shape object")
    if type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise ProposalArtifactError("unsupported reconciliation report schema")
    if report.get("mode") != "proposal-only":
        raise ProposalArtifactError("report must be proposal-only")
    for key in ("roadmap_modified", "github_modified", "task_dispatch_performed"):
        if report.get(key) is not False:
            raise ProposalArtifactError(f"{key} must be false")
    repository = report.get("repository")
    if repository is not None and (
        not isinstance(repository, str) or len(repository) > 200
        or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None
    ):
        raise ProposalArtifactError("repository field is invalid")
    source = report.get("source")
    if source is not None and (not isinstance(source, str) or len(source) > 32):
        raise ProposalArtifactError("source field is invalid")
    snapshots_seen = report.get("issue_snapshots_seen")
    if snapshots_seen is not None and (
        isinstance(snapshots_seen, bool) or not isinstance(snapshots_seen, int)
        or snapshots_seen < 0 or snapshots_seen > 100_000
    ):
        raise ProposalArtifactError("issue_snapshots_seen is invalid")

    proposals = report.get("proposals")
    unchanged = report.get("unchanged")
    if not isinstance(repository, str) or not repository:
        raise ProposalArtifactError("repository is required to validate the proposal artifact")
    if not isinstance(proposals, list) or not isinstance(unchanged, list):
        raise ProposalArtifactError("report proposals and unchanged must be lists")
    if len(proposals) + len(unchanged) > _MAX_REPORT_ITEMS:
        raise ProposalArtifactError("report entry count exceeds the safety limit")

    seen_task_keys: set[str] = set()
    for item in proposals:
        if not isinstance(item, dict) or set(item) - {
            "task_key", "issue_number", "from_status", "to_status",
            "requires_owner_approval", "evidence",
        }:
            raise ProposalArtifactError("proposal entry has an invalid shape")
        task_key = item.get("task_key")
        if not isinstance(task_key, str) or _TASK_KEY.fullmatch(task_key) is None:
            raise ProposalArtifactError("proposal has an invalid task_key")
        if task_key in seen_task_keys:
            raise ProposalArtifactError("report contains duplicate task entries")
        seen_task_keys.add(task_key)
        issue_number = item.get("issue_number")
        if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number < 1:
            raise ProposalArtifactError("proposal has an invalid issue_number")
        if (
            not isinstance(item.get("from_status"), str) or item["from_status"] not in _STATUSES
            or not isinstance(item.get("to_status"), str) or item["to_status"] not in _STATUSES
            or item.get("requires_owner_approval") is not False
        ):
            raise ProposalArtifactError("proposal has an unsupported status or owner gate")
        _validate_evidence(item.get("evidence"), issue_number, repository, require_done=item["to_status"] == "done")

    for item in unchanged:
        if not isinstance(item, dict) or set(item) - {
            "task_key", "status", "reason", "stale", "proposed_status",
            "requires_owner_approval", "evidence", "blocked_by",
        }:
            raise ProposalArtifactError("unchanged entry has an invalid shape")
        task_key = item.get("task_key")
        if not isinstance(task_key, str) or _TASK_KEY.fullmatch(task_key) is None:
            raise ProposalArtifactError("unchanged entry has an invalid task_key")
        if task_key in seen_task_keys:
            raise ProposalArtifactError("report contains duplicate task entries")
        seen_task_keys.add(task_key)
        if not isinstance(item.get("status"), str) or item["status"] not in _STATUSES:
            raise ProposalArtifactError("unchanged entry has an unsupported status")
        if "requires_owner_approval" in item and type(item["requires_owner_approval"]) is not bool:
            raise ProposalArtifactError("owner approval marker must be boolean")
        proposed_status = item.get("proposed_status")
        if proposed_status is not None and (
            not isinstance(proposed_status, str) or proposed_status not in _STATUSES
        ):
            raise ProposalArtifactError("unchanged entry has an unsupported proposed status")
        reason = item.get("reason", "")
        if not isinstance(reason, str) or len(reason) > _MAX_REASON_CHARS or any(
            char in reason for char in "\r\n#*_`[]|>"
        ):
            raise ProposalArtifactError("reason must be short plain text without Markdown structure")
        blocked_by = item.get("blocked_by", [])
        if (
            not isinstance(blocked_by, list) or len(blocked_by) > 100
            or any(not isinstance(dep, str) or _TASK_KEY.fullmatch(dep) is None for dep in blocked_by)
            or len(set(blocked_by)) != len(blocked_by)
        ):
            raise ProposalArtifactError("blocked_by must be a unique list of task keys")
        if proposed_status is not None and item.get("requires_owner_approval") is not True:
            raise ProposalArtifactError("unapproved status change must remain owner-gated")
        if "evidence" in item:
            raw_unchanged_evidence = item["evidence"]
            if not isinstance(raw_unchanged_evidence, dict):
                raise ProposalArtifactError("unchanged evidence must be an object")
            unchanged_issue = raw_unchanged_evidence.get("issue_number")
            if isinstance(unchanged_issue, bool) or not isinstance(unchanged_issue, int) or unchanged_issue < 1:
                raise ProposalArtifactError("unchanged evidence lacks a valid issue reference")
            _validate_evidence(
                raw_unchanged_evidence, unchanged_issue, repository,
                require_done=proposed_status == "done", allow_missing_pr=True,
            )
        if item.get("requires_owner_approval") is True and proposed_status is not None:
            raw_evidence = item.get("evidence")
            if not isinstance(raw_evidence, dict):
                raise ProposalArtifactError("pending owner decision lacks supporting evidence")
            evidence_issue = raw_evidence.get("issue_number")
            if isinstance(evidence_issue, bool) or not isinstance(evidence_issue, int) or evidence_issue < 1:
                raise ProposalArtifactError("pending owner decision lacks a valid issue reference")
            _validate_evidence(raw_evidence, evidence_issue, repository, require_done=proposed_status == "done")

    normalized = dict(report)
    normalized["proposals"] = sorted(proposals, key=lambda item: item["task_key"])
    normalized["unchanged"] = sorted(unchanged, key=lambda item: item["task_key"])
    return normalized


def build_proposal_artifact(report: Any) -> dict[str, Any]:
    """Return stable JSON and Markdown artifacts for a validated report."""
    normalized = _validate_report(report)
    repository = normalized.get("repository")
    if not isinstance(repository, str) or not repository:
        raise ProposalArtifactError("repository is required to render the proposal artifact")
    try:
        canonical = json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise ProposalArtifactError("report cannot be serialized as safe JSON") from exc
    if len(canonical) > _MAX_REPORT_BYTES:
        raise ProposalArtifactError("report exceeds the artifact size limit")
    digest = hashlib.sha256(canonical).hexdigest()
    proposal_id = f"sha256:{digest}"

    lines = [
        "<!-- carautopsy-roadmap-proposal:v1 -->",
        "## Roadmap reconciliation proposal",
        "",
        f"**Proposal ID:** `{proposal_id}`",
        "",
        "**Dry run only. No roadmap, GitHub, workflow, or task-queue changes were applied.**",
        "",
    ]
    if normalized["proposals"]:
        lines.extend([
            "### Proposed status changes",
            "",
            "| Task | Issue | Current | Proposed | PR | Exact head | Merge commit | CI evidence |",
            "|---|---:|---|---|---:|---|---|---|",
        ])
        for item in normalized["proposals"]:
            evidence = item["evidence"]
            check_links = _render_check_links(
                evidence, repository, require_complete=item["to_status"] == "done"
            )
            lines.append(
                f"| `{html.escape(item['task_key'])}` | #{item['issue_number']} "
                f"| {html.escape(item['from_status'])} | {html.escape(item['to_status'])} "
                f"| #{evidence['linked_pr_number']} | `{evidence['head_sha']}` | "
                f"{html.escape(str(evidence.get('merge_commit_sha', '—')))} | {check_links} |"
            )
        lines.append("")
    else:
        lines.extend(["### Proposed status changes", "", "No status changes are eligible.", ""])

    pending = [
        item for item in normalized["unchanged"]
        if item.get("requires_owner_approval") is True and item.get("proposed_status") is not None
    ]
    if pending:
        lines.extend(["### Pending owner approval", ""])
        for item in pending:
            evidence = item["evidence"]
            merge_sha = evidence.get("merge_commit_sha", "—")
            ci_links = _render_check_links(evidence, repository, require_complete=item["proposed_status"] == "done")
            lines.append(
                f"- {html.escape(item['task_key'])}: "
                f"{html.escape(str(item.get('status', 'unknown')))} → "
                f"{html.escape(str(item['proposed_status']))} — owner approval required "
                f"(issue #{evidence['issue_number']}, PR #{evidence['linked_pr_number']}, "
                f"head {evidence['head_sha']}, merge {html.escape(str(merge_sha))}, "
                f"CI: {ci_links})"
            )
        lines.append("")

    blocked = [
        item for item in normalized["unchanged"]
        if item.get("proposed_status") is None
    ]
    if blocked:
        lines.extend(["### Unchanged / blocked", ""])
        for item in blocked:
            reason = html.escape(str(item.get("reason", "No verified status change")))
            blockers = item.get("blocked_by", [])
            suffix = " (blocked by: " + ", ".join(html.escape(dep) for dep in blockers) + ")" if blockers else ""
            lines.append(f"- {html.escape(item['task_key'])}: {reason}{suffix}")
        lines.append("")

    lines.extend([
        "---",
        "This artifact is informational. It is not an approval, merge request, or activation signal.",
    ])
    markdown = "\n".join(lines) + "\n"
    if len(markdown.encode("utf-8")) > _MAX_MARKDOWN_BYTES:
        pending_count = sum(
            item.get("requires_owner_approval") is True and item.get("proposed_status") is not None
            for item in normalized["unchanged"]
        )
        blocked_count = sum(item.get("proposed_status") is None for item in normalized["unchanged"])
        markdown = "\n".join([
            "# Roadmap reconciliation proposal",
            "",
            f"- Proposal ID: `{proposal_id}`",
            f"- Proposed status changes: {len(normalized['proposals'])}",
            f"- Pending owner decisions: {pending_count}",
            f"- Unchanged / blocked tasks: {blocked_count}",
            "",
            "The full deterministic JSON artifact contains every task, evidence record, blocker, and CI reference. "
            "This compact comment is used because the detailed Markdown would exceed the safe comment-size limit.",
            "",
            "This artifact is informational. It is not an approval, merge request, or activation signal.",
        ]) + "\n"
    if len(markdown.encode("utf-8")) > _MAX_MARKDOWN_BYTES:
        raise ProposalArtifactError("summary Markdown exceeds the safe comment size limit")
    return {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "report": normalized,
        "comment_markdown": markdown,
    }


def render_proposal_comment(report: Any) -> str:
    """Render the stable Markdown comment body without publishing it."""
    return build_proposal_artifact(report)["comment_markdown"]


def render_proposal_artifact_json(report: Any) -> str:
    """Serialize the full proposal artifact as deterministic JSON."""
    rendered = json.dumps(
        build_proposal_artifact(report), indent=2, sort_keys=True, ensure_ascii=True,
        allow_nan=False,
    ) + "\n"
    if len(rendered.encode("utf-8")) > _MAX_REPORT_BYTES:
        raise ProposalArtifactError("serialized proposal artifact exceeds the size limit")
    return rendered
