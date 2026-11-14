"""Deterministic, read-only GitHub issue triage for roadmap proposals.

Issue text is untrusted input. This module intentionally classifies only from
repository-maintainer labels and basic GitHub metadata; it never interprets
issue bodies as executable instructions or applies roadmap changes.
"""

from __future__ import annotations

from typing import Any


_LABEL_CLASSIFICATIONS = {
    "roadmap:candidate": "actionable",
    "roadmap:informational": "informational",
    "roadmap:blocked": "blocked",
    "roadmap:duplicate": "duplicate",
    "roadmap:triage": "needs-owner-triage",
}


class IssueClassificationError(ValueError):
    """Raised when an issue snapshot is malformed or ambiguous."""


def _issue_labels(issue: dict[str, Any]) -> set[str]:
    raw_labels = issue.get("labels", [])
    if not isinstance(raw_labels, list):
        raise IssueClassificationError("issue labels must be a list")

    labels: set[str] = set()
    for item in raw_labels:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name")
        else:
            raise IssueClassificationError("issue label entries must be strings or objects")
        if not isinstance(name, str) or not name.strip():
            raise IssueClassificationError("issue label name must be a non-empty string")
        labels.add(name.strip().lower())
    return labels


def classify_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Return a stable classification; never mutate the input or roadmap.

    Explicit maintainer labels are the only signal that can make an issue
    actionable. Unknown, missing, or conflicting labels fail closed to
    needs-owner-triage. Pull requests are excluded from issue intake.
    """
    if not isinstance(issue, dict):
        raise IssueClassificationError("issue snapshot must be an object")

    number = issue.get("number")
    title = issue.get("title")
    state = issue.get("state")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise IssueClassificationError("issue number must be a positive integer")
    if not isinstance(title, str) or not title.strip():
        raise IssueClassificationError("issue title must be a non-empty string")
    if not isinstance(state, str) or state not in {"open", "closed"}:
        raise IssueClassificationError("issue state must be open or closed")

    labels = _issue_labels(issue)
    issue_url = issue.get("html_url")
    if issue_url is not None and not isinstance(issue_url, str):
        raise IssueClassificationError("issue html_url must be a string when provided")

    if "pull_request" in issue:
        classification = "not-an-issue"
        reason = "GitHub pull requests are excluded from issue intake."
    elif state == "closed":
        classification = "closed"
        reason = "Closed issues do not create new roadmap proposals."
    else:
        unknown_roadmap_labels = sorted(
            label
            for label in labels
            if label.startswith("roadmap:") and label not in _LABEL_CLASSIFICATIONS
        )
        matches = sorted(label for label in labels if label in _LABEL_CLASSIFICATIONS)
        if unknown_roadmap_labels:
            classification = "needs-owner-triage"
            reason = (
                "Unknown roadmap namespace label(s) require owner review: "
                + ", ".join(unknown_roadmap_labels)
                + "."
            )
        elif len(matches) == 1:
            classification = _LABEL_CLASSIFICATIONS[matches[0]]
            reason = f"Classified by maintainer label: {matches[0]}."
        elif len(matches) > 1:
            classification = "needs-owner-triage"
            reason = "Conflicting roadmap classification labels require owner review."
        else:
            classification = "needs-owner-triage"
            reason = "No recognized maintainer roadmap classification label is present."

    proposal = None
    if classification == "actionable":
        proposal = {
            "task_key": f"issue-{number}",
            "issue_number": number,
            "issue_url": issue_url,
            "title": title.strip(),
            "status": "proposed",
            "dependencies": [],
            "acceptance_criteria": [],
            "owner_actions": [
                "Owner must supply dependencies and acceptance criteria before approval."
            ],
            "owner_input_required": True,
            "status": "proposed",
            "requires_owner_approval": True,
        }

    return {
        "issue_number": number,
        "issue_url": issue_url,
        "title": title.strip(),
        "classification": classification,
        "labels": sorted(labels),
        "reason": reason,
        "proposal": proposal,
    }


def build_issue_proposals(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify a collection and return only owner-gated proposal records."""
    if not isinstance(issues, list):
        raise IssueClassificationError("issues must be a list")

    grouped: dict[int, list[dict[str, Any]]] = {}
    for snapshot in issues:
        result = classify_issue(snapshot)
        grouped.setdefault(result["issue_number"], []).append(result)

    proposals = []
    for number in sorted(grouped):
        snapshots = grouped[number]
        # Collapse identical normalized snapshots; conflicting versions fail closed.
        canonical = {
            (
                item["issue_url"],
                item["title"],
                item["classification"],
                tuple(item["labels"]),
            )
            for item in snapshots
        }
        if len(canonical) != 1:
            proposals.append(
                {
                    "task_key": f"issue-{number}",
                    "issue_number": number,
                    "issue_url": None,
                    "title": f"Conflicting snapshots for issue #{number}",
                    "classification": "needs-owner-triage",
                    "reason": "Conflicting issue snapshots require owner review.",
                    "proposal": None,
                    "status": "needs-owner-triage",
                    "requires_owner_approval": True,
                }
            )
            continue
        proposal = snapshots[0]["proposal"]
        if proposal is not None:
            proposals.append(proposal)
    return proposals
