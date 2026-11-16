"""Deterministic proposal artifact and comment renderer.

Rendering is side-effect free. It never posts comments or modifies roadmap state.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import re
from typing import Any


class ProposalArtifactError(ValueError):
    """Raised when a reconciliation report is not safe to render."""


_TASK_KEY = re.compile(r"[a-z0-9][a-z0-9-]{1,63}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_STATUSES = {"proposed", "approved", "blocked", "in_progress", "done", "needs-owner-triage"}
_MAX_REPORT_ITEMS = 5000
_MAX_REPORT_BYTES = 5_000_000
_MAX_MARKDOWN_BYTES = 60_000


def _validate_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise ProposalArtifactError("reconciliation report must be an object")
    if type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise ProposalArtifactError("unsupported reconciliation report schema")
    if report.get("mode") != "proposal-only":
        raise ProposalArtifactError("report must be proposal-only")
    for key in ("roadmap_modified", "github_modified", "task_dispatch_performed"):
        if report.get(key) is not False:
            raise ProposalArtifactError(f"{key} must be false")
    proposals = report.get("proposals")
    unchanged = report.get("unchanged")
    if not isinstance(proposals, list) or not isinstance(unchanged, list):
        raise ProposalArtifactError("report proposals and unchanged must be lists")
    if len(proposals) + len(unchanged) > _MAX_REPORT_ITEMS:
        raise ProposalArtifactError("report entry count exceeds the safety limit")

    seen_task_keys: set[str] = set()
    for item in proposals:
        if not isinstance(item, dict):
            raise ProposalArtifactError("proposal entry must be an object")
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
            not isinstance(item.get("from_status"), str)
            or item["from_status"] not in _STATUSES
            or not isinstance(item.get("to_status"), str)
            or item["to_status"] not in _STATUSES
        ):
            raise ProposalArtifactError("proposal has an unsupported status")
        if item.get("requires_owner_approval") is not False:
            raise ProposalArtifactError("renderable proposal must already have explicit owner approval")
        evidence = item.get("evidence")
        evidence_issue = evidence.get("issue_number") if isinstance(evidence, dict) else None
        if (
            not isinstance(evidence, dict)
            or isinstance(evidence_issue, bool)
            or not isinstance(evidence_issue, int)
            or evidence_issue != issue_number
        ):
            raise ProposalArtifactError("proposal evidence does not match its issue")
        head_sha = evidence.get("head_sha")
        if not isinstance(head_sha, str) or _SHA.fullmatch(head_sha) is None:
            raise ProposalArtifactError("proposal evidence lacks an exact PR head SHA")
        linked_pr = evidence.get("linked_pr_number")
        if isinstance(linked_pr, bool) or not isinstance(linked_pr, int) or linked_pr < 1:
            raise ProposalArtifactError("proposal evidence lacks a linked PR number")
        if item["to_status"] == "done":
            merge_sha = evidence.get("merge_commit_sha")
            if not isinstance(merge_sha, str) or _SHA.fullmatch(merge_sha) is None:
                raise ProposalArtifactError("done proposal evidence lacks a valid merge commit SHA")

    for item in unchanged:
        if not isinstance(item, dict):
            raise ProposalArtifactError("unchanged entry must be an object")
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
        if "reason" in item and (
            not isinstance(item["reason"], str) or len(item["reason"]) > 4000
        ):
            raise ProposalArtifactError("unchanged entry reason must be text within the length limit")
        if item.get("requires_owner_approval") is True and proposed_status is not None:
            evidence = item.get("evidence")
            if not isinstance(evidence, dict):
                raise ProposalArtifactError("pending owner decision lacks supporting evidence")
            evidence_issue = evidence.get("issue_number")
            linked_pr = evidence.get("linked_pr_number")
            head_sha = evidence.get("head_sha")
            merge_sha = evidence.get("merge_commit_sha")
            if (
                isinstance(evidence_issue, bool) or not isinstance(evidence_issue, int) or evidence_issue < 1
                or isinstance(linked_pr, bool) or not isinstance(linked_pr, int) or linked_pr < 1
                or not isinstance(head_sha, str) or _SHA.fullmatch(head_sha) is None
                or (merge_sha is not None and (
                    not isinstance(merge_sha, str) or _SHA.fullmatch(merge_sha) is None
                ))
                or (proposed_status == "done" and merge_sha is None)
            ):
                raise ProposalArtifactError("pending owner decision has incomplete supporting evidence")

    try:
        normalized = copy.deepcopy(report)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProposalArtifactError("report could not be safely copied") from exc
    normalized["proposals"] = sorted(normalized["proposals"], key=lambda item: item["task_key"])
    normalized["unchanged"] = sorted(normalized["unchanged"], key=lambda item: item["task_key"])
    try:
        json.dumps(normalized, sort_keys=True, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProposalArtifactError("report is not valid finite JSON data") from exc
    return normalized


def build_proposal_artifact(report: Any) -> dict[str, Any]:
    """Return stable JSON and Markdown artifacts for a validated report."""
    normalized = _validate_report(report)
    canonical = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
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
            "| Task | Issue | Current | Proposed | PR | Exact head | Merge commit |",
            "|---|---:|---|---|---:|---|---|",
        ])
        for item in normalized["proposals"]:
            evidence = item["evidence"]
            lines.append(
                f"| `{html.escape(item['task_key'])}` | #{item['issue_number']} "
                f"| {html.escape(item['from_status'])} | {html.escape(item['to_status'])} "
                f"| #{evidence['linked_pr_number']} | `{evidence['head_sha']}` | "
                f"{html.escape(str(evidence.get('merge_commit_sha', '—')))} |"
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
            lines.append(
                f"- `{html.escape(item['task_key'])}`: "
                f"{html.escape(str(item.get('status', 'unknown')))} → "
                f"{html.escape(str(item['proposed_status']))} — owner approval required "
                f"(issue #{evidence['issue_number']}, PR #{evidence['linked_pr_number']}, "
                f"head `{evidence['head_sha']}`, merge {html.escape(str(merge_sha))})"
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
            lines.append(f"- `{html.escape(item['task_key'])}`: {reason}")
        lines.append("")

    lines.extend([
        "---",
        "This artifact is informational. It is not an approval, merge request, or activation signal.",
    ])
    markdown = "\n".join(lines) + "\n"
    if len(markdown.encode("utf-8")) > _MAX_MARKDOWN_BYTES:
        raise ProposalArtifactError("Markdown proposal exceeds the safe comment size limit")
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
