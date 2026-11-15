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
from pathlib import Path
from typing import Any

import requests

from issue_roadmap import IssueClassificationError, build_issue_proposals


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


def fetch_open_issues(
    repository: str,
    token: str | None = None,
    *,
    session: Any = requests,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    """Fetch open issue snapshots from the fixed GitHub API endpoint.

    Only scalar metadata used by the classifier is retained. Issue bodies,
    nested label metadata, and the nested pull-request API object are discarded.
    """
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
    for page in range(1, MAX_PAGES + 1):
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
        if not payload:
            return issues

        for item in payload:
            if not isinstance(item, dict):
                raise IntakeControllerError("GitHub issues endpoint returned a malformed item")
            raw_labels = item.get("labels", [])
            if not isinstance(raw_labels, list):
                raise IntakeControllerError("GitHub issue labels must be a list")
            labels: list[str] = []
            for label in raw_labels:
                name_value = label if isinstance(label, str) else (
                    label.get("name") if isinstance(label, dict) else None
                )
                if not isinstance(name_value, str) or not name_value.strip():
                    raise IntakeControllerError("GitHub issue contains a malformed label")
                labels.append(name_value)

            snapshot = {
                key: item[key]
                for key in ("number", "title", "state", "html_url")
                if key in item
            }
            snapshot["labels"] = labels
            if "pull_request" in item:
                # The classifier only needs the marker's presence, not its URL.
                snapshot["pull_request"] = True
            issues.append(snapshot)

        if len(payload) < per_page:
            return issues

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
    return payload


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
    actionable = sum(item.get("classification") == "actionable" for item in proposals)
    triage = sum(item.get("classification") == "needs-owner-triage" for item in proposals)
    return {
        "schema_version": 1,
        "mode": "dry-run",
        "repository": repository,
        "source": source,
        "issue_snapshots_seen": len(issues),
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
    """Serialize a stable JSON artifact suitable for diffing and retries."""
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


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
        sys.stdout.write(render_report(report))
        return 0
    except (IntakeControllerError, IssueClassificationError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
