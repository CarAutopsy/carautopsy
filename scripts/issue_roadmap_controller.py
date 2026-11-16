"""Read-only GitHub issue intake controller.

This CLI fetches open issue metadata or consumes a fixture, applies the pure
classifier, and emits a deterministic owner-gated proposal artifact to stdout.
It never writes to GitHub, the roadmap, labels, workflows, or task queues.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from issue_roadmap import IssueClassificationError, build_issue_proposals, classify_issue
from issue_roadmap_sync import RoadmapReconciliationError, build_reconciliation_proposal
from issue_roadmap_proposal import ProposalArtifactError, render_proposal_comment


GITHUB_API = "https://api.github.com"
MAX_PAGES = 1000


class IntakeControllerError(RuntimeError):
    """Raised when issue intake cannot safely complete."""


def _validate_repository(repository: str) -> tuple[str, str]:
    if not isinstance(repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ):
        raise IntakeControllerError("repository must use owner/name form")
    owner, name = repository.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise IntakeControllerError("repository owner and name must be valid path segments")
    return owner, name


def _project_issue_snapshot(item: Any) -> dict[str, Any]:
    """Keep only the primitive metadata required by the classifier."""
    if not isinstance(item, dict):
        raise IntakeControllerError("issue snapshot must be an object")
    raw_labels = item.get("labels", [])
    if not isinstance(raw_labels, list):
        raise IntakeControllerError("issue labels must be a list")
    labels: list[str] = []
    for label in raw_labels:
        name_value = label if isinstance(label, str) else (
            label.get("name") if isinstance(label, dict) else None
        )
        if not isinstance(name_value, str) or not name_value.strip():
            raise IntakeControllerError("issue contains a malformed label")
        labels.append(name_value)

    snapshot = {
        key: item[key]
        for key in ("number", "title", "state", "html_url")
        if key in item
    }
    snapshot["labels"] = labels
    if "pull_request" in item:
        # Any present marker, including a malformed/falsy one, fails closed.
        snapshot["pull_request"] = True
    return snapshot


def _next_page_from_link(link: Any, *, owner: str, repository: str, current_page: int) -> int:
    """Validate GitHub's next link and require strictly sequential pagination."""
    if not isinstance(link, dict) or not isinstance(link.get("url"), str):
        raise IntakeControllerError("GitHub returned a malformed pagination link")
    try:
        parsed = urlsplit(link["url"])
        expected_path = f"/repos/{owner}/{repository}/issues"
        repository_id_path = re.fullmatch(r"/repositories/[0-9]+/issues", parsed.path)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.github.com"
            or (parsed.path != expected_path and repository_id_path is None)
        ):
            raise IntakeControllerError("GitHub returned an unexpected pagination URL")

        page_values = parse_qs(parsed.query).get("page", [])
        if len(page_values) != 1 or re.fullmatch(r"[0-9]+", page_values[0]) is None:
            raise IntakeControllerError("GitHub pagination link has an invalid page number")
        next_page = int(page_values[0])
    except ValueError as exc:
        # urlsplit can reject malformed bracketed authorities; keep all
        # untrusted pagination parsing failures inside the controlled CLI path.
        raise IntakeControllerError("GitHub returned a malformed pagination link") from exc

    if next_page != current_page + 1:
        raise IntakeControllerError("GitHub pagination link skipped or repeated a page")
    if next_page > MAX_PAGES:
        raise IntakeControllerError(f"GitHub pagination exceeded {MAX_PAGES} pages")
    return next_page


def fetch_issue_snapshots(
    repository: str,
    token: str | None = None,
    *,
    state: str = "open",
    session: Any = requests,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    """Fetch issue snapshots for one explicit GitHub state filter."""
    owner, name = _validate_repository(repository)
    if state not in {"open", "closed", "all"}:
        raise IntakeControllerError("state must be open, closed, or all")
    if isinstance(per_page, bool) or not isinstance(per_page, int) or not 1 <= per_page <= 100:
        raise IntakeControllerError("per_page must be an integer from 1 to 100")

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    issues: list[dict[str, Any]] = []
    page = 1
    while page <= MAX_PAGES:
        try:
            response = session.get(
                f"{GITHUB_API}/repos/{owner}/{name}/issues",
                params={"state": state, "per_page": per_page, "page": page},
                headers=headers,
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            # Do not include exception text: HTTP client errors can contain
            # request details, and this CLI must never print authorization data.
            raise IntakeControllerError(
                f"GitHub issue fetch failed on page {page} ({type(exc).__name__})"
            ) from exc

        if not isinstance(payload, list):
            raise IntakeControllerError("GitHub issues endpoint returned a non-list payload")
        issues.extend(_project_issue_snapshot(item) for item in payload)

        links = getattr(response, "links", {})
        if not isinstance(links, dict):
            links = {}
        next_link = links.get("next")
        if next_link is None:
            return issues
        page = _next_page_from_link(
            next_link, owner=owner, repository=name, current_page=page
        )

    raise IntakeControllerError(f"GitHub pagination exceeded {MAX_PAGES} pages")


def fetch_open_issues(
    repository: str,
    token: str | None = None,
    *,
    session: Any = requests,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    """Backward-compatible open-issues fetch helper."""
    return fetch_issue_snapshots(
        repository, token, state="open", session=session, per_page=per_page
    )


def load_issue_fixture(path: str | Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise IntakeControllerError(f"could not read issue fixture ({type(exc).__name__})") from exc

    if isinstance(payload, dict):
        payload = payload.get("issues")
    if not isinstance(payload, list):
        raise IntakeControllerError("fixture must be a JSON array or an object with an issues array")
    return [_project_issue_snapshot(item) for item in payload]


def _project_records(payload: Any, fields: tuple[str, ...], label: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise IntakeControllerError(f"{label} must be a list")
    projected = []
    for item in payload:
        if not isinstance(item, dict):
            raise IntakeControllerError(f"{label} entries must be objects")
        projected.append({key: item[key] for key in fields if key in item})
    return projected


def load_reconciliation_fixture(path: str | Path) -> dict[str, Any]:
    """Load a reconciliation fixture while discarding bodies and unrelated fields."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise IntakeControllerError(
            f"could not read reconciliation fixture ({type(exc).__name__})"
        ) from exc
    if not isinstance(payload, dict):
        raise IntakeControllerError("reconciliation fixture must be a JSON object")

    repository = payload.get("repository", "CarAutopsy/carautopsy")
    _validate_repository(repository)
    if payload.get("approved_task_keys") not in (None, []):
        raise IntakeControllerError("fixture input cannot assert owner approval")
    if payload.get("required_checks") not in (None, ["audit", "validate"]):
        raise IntakeControllerError("fixture input cannot override required CI checks")

    return {
        "repository": repository,
        "roadmap_tasks": _project_records(
            payload.get("roadmap_tasks"),
            ("task_key", "issue_number", "status", "dependencies", "source_updated_at"),
            "roadmap_tasks",
        ),
        "issue_snapshots": _project_records(
            payload.get("issue_snapshots"),
            ("number", "state", "updated_at"),
            "issue_snapshots",
        ),
        "pull_request_evidence": _project_records(
            payload.get("pull_request_evidence"),
            ("number", "issue_number", "state", "merged", "head_sha", "merge_commit_sha", "link_evidence"),
            "pull_request_evidence",
        ),
        "check_runs": _project_records(
            payload.get("check_runs"),
            ("id", "name", "head_sha", "conclusion", "html_url"),
            "check_runs",
        ),
    }


def build_reconciliation_dry_run_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a fixture-backed reconciliation proposal without applying it."""
    try:
        report = build_reconciliation_proposal(
            payload["roadmap_tasks"],
            payload["issue_snapshots"],
            payload["pull_request_evidence"],
            payload["check_runs"],
            approved_task_keys=set(),
            repository=payload["repository"],
        )
    except (KeyError, RoadmapReconciliationError) as exc:
        raise IntakeControllerError(f"reconciliation input rejected ({type(exc).__name__})") from exc
    report["repository"] = payload["repository"]
    report["source"] = "fixture"
    report["issue_snapshots_seen"] = len(payload["issue_snapshots"])
    return report


def build_dry_run_report(
    issues: list[dict[str, Any]],
    *,
    repository: str,
    source: str,
) -> dict[str, Any]:
    _validate_repository(repository)
    if source not in {"fixture", "github-open-issues", "github-closed-issues", "github-all-issues"}:
        raise IntakeControllerError("unsupported intake source")

    proposals = build_issue_proposals(issues)
    classification_counts = Counter(
        classify_issue(snapshot)["classification"] for snapshot in issues
    )
    actionable = sum(item.get("classification") == "actionable" for item in proposals)
    triage = sum(item.get("classification") == "needs-owner-triage" for item in proposals)
    return {
        "schema_version": 1,
        "mode": "dry-run",
        "repository": repository,
        "source": source,
        "issue_snapshots_seen": len(issues),
        "snapshot_classification_counts": dict(sorted(classification_counts.items())),
        "proposal_count": len(proposals),
        "actionable_proposal_count": actionable,
        "owner_triage_count": triage,
        "requires_owner_approval": True,
        "roadmap_modified": False,
        "github_modified": False,
        "task_dispatch_performed": False,
        "proposals": proposals,
    }


def render_report(report: dict[str, Any]) -> str:
    """Serialize stable ASCII JSON suitable for diffing and terminal output."""
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _silence_broken_stdout() -> None:
    """Redirect fd 1 before detaching a failed stream to prevent shutdown flush errors."""
    stream = sys.stdout
    try:
        if stream is not None:
            null_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(null_fd, stream.fileno())
            finally:
                os.close(null_fd)
    except (OSError, ValueError, AttributeError, TypeError):
        # Test doubles and non-file streams may not expose a file descriptor.
        pass
    # This entry point exits immediately after parser.exit; the descriptor above
    # ensures a buffered real stdout can be flushed safely during destruction.
    sys.stdout = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a read-only, owner-gated GitHub issue roadmap proposal."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="JSON fixture containing issue snapshots")
    source.add_argument("--reconcile-input", help="JSON fixture containing roadmap and verified GitHub evidence snapshots")
    source.add_argument(
        "--fetch-github",
        action="store_true",
        help="fetch open issue metadata from the GitHub API (read-only)",
    )
    parser.add_argument("--render-proposal", action="store_true", help="render reconciliation report as a stable Markdown proposal comment (stdout only)")
    parser.add_argument("--repo", default="CarAutopsy/carautopsy", help="GitHub repository owner/name")
    parser.add_argument("--state", choices=("open", "closed", "all"), default=None, help="issue state filter for --fetch-github (default: open)")
    args = parser.parse_args(argv)

    try:
        if args.render_proposal and not args.reconcile_input:
            raise IntakeControllerError("--render-proposal requires --reconcile-input")
        if args.state is not None and not args.fetch_github:
            raise IntakeControllerError("--state is only valid with --fetch-github")
        if args.reconcile_input:
            reconciliation = load_reconciliation_fixture(args.reconcile_input)
            report = build_reconciliation_dry_run_report(reconciliation)
        elif args.fetch_github:
            issues = fetch_issue_snapshots(
                args.repo, os.environ.get("GITHUB_TOKEN"), state=args.state or "open"
            )
            source_name = f"github-{args.state or 'open'}-issues"
            report = build_dry_run_report(issues, repository=args.repo, source=source_name)
        else:
            issues = load_issue_fixture(args.input)
            source_name = "fixture"
            report = build_dry_run_report(
                issues, repository=args.repo, source=source_name
            )
        try:
            rendered = render_proposal_comment(report) if args.render_proposal else render_report(report)
            sys.stdout.write(rendered)
            sys.stdout.flush()
        except (OSError, UnicodeError) as exc:
            _silence_broken_stdout()
            parser.exit(2, f"error: could not write report to stdout ({type(exc).__name__})\n")
        return 0
    except (IntakeControllerError, IssueClassificationError, ProposalArtifactError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
