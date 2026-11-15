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
    """Validate GitHub's next link but continue through our fixed API endpoint."""
    if not isinstance(link, dict) or not isinstance(link.get("url"), str):
        raise IntakeControllerError("GitHub returned a malformed pagination link")
    parsed = urlsplit(link["url"])
    expected_path = f"/repos/{owner}/{repository}/issues"
    if parsed.scheme != "https" or parsed.netloc != "api.github.com" or parsed.path != expected_path:
        raise IntakeControllerError("GitHub returned an unexpected pagination URL")
    page_values = parse_qs(parsed.query).get("page", [])
    if len(page_values) != 1 or not page_values[0].isdigit():
        raise IntakeControllerError("GitHub pagination link has an invalid page number")
    next_page = int(page_values[0])
    if next_page <= current_page:
        raise IntakeControllerError("GitHub pagination link did not advance")
    if next_page > MAX_PAGES:
        raise IntakeControllerError(f"GitHub pagination exceeded {MAX_PAGES} pages")
    return next_page


def fetch_open_issues(
    repository: str,
    token: str | None = None,
    *,
    session: Any = requests,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    """Fetch open issue snapshots from the fixed GitHub API endpoint."""
    owner, name = _validate_repository(repository)
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
                params={"state": "open", "per_page": per_page, "page": page},
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


def load_issue_fixture(path: str | Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntakeControllerError(f"could not read issue fixture ({type(exc).__name__})") from exc

    if isinstance(payload, dict):
        payload = payload.get("issues")
    if not isinstance(payload, list):
        raise IntakeControllerError("fixture must be a JSON array or an object with an issues array")
    return [_project_issue_snapshot(item) for item in payload]


def build_dry_run_report(
    issues: list[dict[str, Any]],
    *,
    repository: str,
    source: str,
) -> dict[str, Any]:
    _validate_repository(repository)
    if source not in {"fixture", "github-open-issues"}:
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
    source.add_argument(
        "--fetch-github",
        action="store_true",
        help="fetch open issue metadata from the GitHub API (read-only)",
    )
    parser.add_argument("--repo", default="CarAutopsy/carautopsy", help="GitHub repository owner/name")
    args = parser.parse_args(argv)

    try:
        if args.fetch_github:
            issues = fetch_open_issues(args.repo, os.environ.get("GITHUB_TOKEN"))
            source_name = "github-open-issues"
        else:
            issues = load_issue_fixture(args.input)
            source_name = "fixture"

        report = build_dry_run_report(
            issues, repository=args.repo, source=source_name
        )
        try:
            sys.stdout.write(render_report(report))
            sys.stdout.flush()
        except (OSError, UnicodeError) as exc:
            _silence_broken_stdout()
            parser.exit(2, f"error: could not write report to stdout ({type(exc).__name__})\n")
        return 0
    except (IntakeControllerError, IssueClassificationError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
