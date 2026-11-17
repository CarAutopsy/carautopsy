"""Bounded, read-only GitHub evidence collector for roadmap reconciliation.

Only GitHub timeline cross-reference events establish issue-to-PR linkage.
Issue/PR bodies, comments, labels, and AI output are never interpreted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from issue_roadmap_controller import IntakeControllerError, _validate_repository
from issue_roadmap_sync import build_reconciliation_proposal

GITHUB_API = "https://api.github.com"
MAX_PAGES = 100
MAX_ISSUES = 500
MAX_PRS = 1000
MAX_CHECK_RUNS = 10000


class EvidenceCollectionError(RuntimeError):
    """Raised when live GitHub evidence cannot be collected safely."""


def _headers(token: str | None) -> dict[str, str]:
    result = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        result["Authorization"] = f"Bearer {token}"
    return result


def _next_page(response: Any, endpoint: str, page: int) -> int | None:
    links = getattr(response, "links", {})
    if not isinstance(links, dict) or "next" not in links:
        return None
    link = links["next"]
    if not isinstance(link, dict) or not isinstance(link.get("url"), str):
        raise EvidenceCollectionError("GitHub returned a malformed pagination link")
    try:
        parsed = urlsplit(link["url"])
        if parsed.scheme != "https" or parsed.netloc != "api.github.com" or parsed.path != endpoint:
            raise EvidenceCollectionError("GitHub returned an unexpected pagination URL")
        values = parse_qs(parsed.query).get("page", [])
        if len(values) != 1 or re.fullmatch(r"[0-9]+", values[0]) is None:
            raise EvidenceCollectionError("GitHub pagination page is malformed")
        next_page = int(values[0])
    except ValueError as exc:
        raise EvidenceCollectionError("GitHub returned a malformed pagination URL") from exc
    if next_page != page + 1 or next_page > MAX_PAGES:
        raise EvidenceCollectionError("GitHub pagination skipped, repeated, or exceeded its limit")
    return next_page


def _get(session: Any, url: str, *, params: dict[str, Any] | None, headers: dict[str, str]) -> Any:
    try:
        response = session.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        return response
    except (requests.RequestException, ValueError) as exc:
        raise EvidenceCollectionError(f"GitHub evidence request failed ({type(exc).__name__})") from exc


def _json(response: Any) -> Any:
    try:
        return response.json()
    except (ValueError, TypeError) as exc:
        raise EvidenceCollectionError("GitHub evidence endpoint returned invalid JSON") from exc


def _paginate(session: Any, url: str, endpoint: str, headers: dict[str, str], *, array_key: str | None = None) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    page = 1
    while page <= MAX_PAGES:
        response = _get(session, url, params={"per_page": 100, "page": page}, headers=headers)
        payload = _json(response)
        records = payload if array_key is None else (payload.get(array_key) if isinstance(payload, dict) else None)
        if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
            raise EvidenceCollectionError("GitHub evidence endpoint returned an invalid collection")
        output.extend(records)
        if len(output) > MAX_CHECK_RUNS:
            raise EvidenceCollectionError("GitHub evidence collection exceeded its record limit")
        next_page = _next_page(response, endpoint, page)
        if next_page is None:
            return output
        page = next_page
    raise EvidenceCollectionError("GitHub evidence pagination exceeded its limit")


def _fetch_timeline_links(owner: str, repo: str, issue_number: int, headers: dict[str, str], session: Any) -> list[int]:
    endpoint = f"/repos/{owner}/{repo}/issues/{issue_number}/timeline"
    records = _paginate(session, f"{GITHUB_API}{endpoint}", endpoint, headers)
    linked: set[int] = set()
    for event in records:
        if event.get("event") != "cross-referenced":
            continue
        source = event.get("source")
        source_issue = source.get("issue") if isinstance(source, dict) else None
        if not isinstance(source_issue, dict) or not isinstance(source_issue.get("pull_request"), dict):
            continue
        source_repository = source_issue.get("repository")
        source_full_name = source_repository.get("full_name") if isinstance(source_repository, dict) else None
        source_repository_url = source_issue.get("repository_url")
        url_full_name = None
        if source_repository_url is not None:
            if not isinstance(source_repository_url, str):
                raise EvidenceCollectionError("GitHub cross-reference event has an invalid source repository URL")
            parsed_repository_url = urlsplit(source_repository_url)
            expected_path = f"/repos/{owner}/{repo}"
            if (
                parsed_repository_url.scheme != "https"
                or parsed_repository_url.netloc != "api.github.com"
                or parsed_repository_url.path.count("/") != 3
                or parsed_repository_url.query
                or parsed_repository_url.fragment
            ):
                raise EvidenceCollectionError("GitHub cross-reference event has an invalid source repository URL")
            parts = parsed_repository_url.path.split("/")
            if len(parts) == 4 and parts[1] == "repos":
                url_full_name = f"{parts[2]}/{parts[3]}"
            else:
                raise EvidenceCollectionError("GitHub cross-reference event has an invalid source repository URL")
        if source_full_name is not None and (
            not isinstance(source_full_name, str)
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source_full_name) is None
        ):
            raise EvidenceCollectionError("GitHub cross-reference event has an invalid source repository identity")
        if source_full_name is None:
            source_full_name = url_full_name
        elif url_full_name is not None and source_full_name.casefold() != url_full_name.casefold():
            raise EvidenceCollectionError("GitHub cross-reference repository identities conflict")
        if source_full_name is None:
            raise EvidenceCollectionError("GitHub cross-reference event lacks a valid source repository identity")
        if source_full_name.casefold() != f"{owner}/{repo}".casefold():
            continue
        number = source_issue.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise EvidenceCollectionError("GitHub cross-reference event has an invalid PR number")
        linked.add(number)
    return sorted(linked)


def _fetch_pr(owner: str, repo: str, number: int, headers: dict[str, str], session: Any) -> dict[str, Any]:
    response = _get(session, f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}", params=None, headers=headers)
    payload = _json(response)
    if not isinstance(payload, dict) or payload.get("number") != number:
        raise EvidenceCollectionError("GitHub pull request endpoint returned an invalid object")
    head = payload.get("head")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    state, merged, merge_sha = payload.get("state"), payload.get("merged"), payload.get("merge_commit_sha")
    if (
        not isinstance(head_sha, str) or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None
        or state not in {"open", "closed"} or type(merged) is not bool
        or (merged and (state != "closed" or not isinstance(merge_sha, str)
                        or re.fullmatch(r"[0-9a-f]{40}", merge_sha) is None))
    ):
        raise EvidenceCollectionError("GitHub pull request metadata is malformed")
    return {"number": number, "state": state, "merged": merged, "head_sha": head_sha, "merge_commit_sha": merge_sha}


def collect_github_evidence(repository: str, issue_snapshots: list[dict[str, Any]], *, token: str | None = None, session: Any = requests) -> dict[str, list[dict[str, Any]]]:
    """Collect timeline-linked PR metadata and exact-head check runs."""
    try:
        owner, repo = _validate_repository(repository)
    except IntakeControllerError as exc:
        raise EvidenceCollectionError("repository must use owner/name form") from exc
    if not isinstance(issue_snapshots, list) or len(issue_snapshots) > MAX_ISSUES:
        raise EvidenceCollectionError("issue snapshots must be a bounded list")
    headers = _headers(token)
    issue_numbers: set[int] = set()
    for issue in issue_snapshots:
        if not isinstance(issue, dict) or set(issue) - {"number", "state", "updated_at"}:
            raise EvidenceCollectionError("issue snapshot contains unsupported fields")
        number = issue.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise EvidenceCollectionError("issue snapshot has an invalid number")
        if number in issue_numbers:
            raise EvidenceCollectionError("duplicate issue snapshots are ambiguous")
        if issue.get("state") not in {"open", "closed"}:
            raise EvidenceCollectionError("issue snapshot has an invalid state")
        if not isinstance(issue.get("updated_at"), str):
            raise EvidenceCollectionError("issue snapshot lacks updated_at")
        issue_numbers.add(number)

    links: set[tuple[int, int]] = set()
    distinct_pr_numbers: set[int] = set()
    for issue_number in sorted(issue_numbers):
        for pr_number in _fetch_timeline_links(owner, repo, issue_number, headers, session):
            links.add((issue_number, pr_number))
            distinct_pr_numbers.add(pr_number)
            if len(distinct_pr_numbers) > MAX_PRS:
                raise EvidenceCollectionError("linked PR count exceeds the safety limit")

    pr_numbers = sorted({number for _, number in links})
    pr_records = {number: _fetch_pr(owner, repo, number, headers, session) for number in pr_numbers}
    evidence = [
        {**pr_records[pr_number], "issue_number": issue_number,
         "link_evidence": "github-cross-reference-event"}
        for issue_number, pr_number in sorted(links)
    ]

    all_checks: list[dict[str, Any]] = []
    # A commit may be the head of several PRs. Fetch its check snapshot once so
    # duplicate PR references cannot observe different in-flight conclusions.
    for head_sha in sorted({record["head_sha"] for record in pr_records.values()}):
        endpoint = f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs"
        runs = _paginate(session, f"{GITHUB_API}{endpoint}", endpoint, headers, array_key="check_runs")
        projected_runs: list[dict[str, Any]] = []
        for run in runs:
            observed_sha = run.get("head_sha")
            if observed_sha != head_sha:
                raise EvidenceCollectionError("check-run head SHA does not match the requested PR head")
            projected_runs.append({
                "id": run.get("id"), "name": run.get("name"), "head_sha": observed_sha,
                "conclusion": run.get("conclusion"), "html_url": run.get("html_url"),
            })
        all_checks.extend(projected_runs)
        if len(all_checks) > MAX_CHECK_RUNS:
            raise EvidenceCollectionError("check-run count exceeds the safety limit")
    unique_checks: dict[int, dict[str, Any]] = {}
    for item in all_checks:
        check_id = item["id"]
        if isinstance(check_id, bool) or not isinstance(check_id, int) or check_id < 1:
            continue
        previous = unique_checks.get(check_id)
        if previous is not None and previous != item:
            raise EvidenceCollectionError("GitHub returned conflicting records for one check-run ID")
        unique_checks[check_id] = item
    return {"pull_request_evidence": evidence, "check_runs": [unique_checks[key] for key in sorted(unique_checks)]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect read-only GitHub evidence for roadmap reconciliation.")
    parser.add_argument("--input", required=True, help="JSON with repository, roadmap_tasks, and issue_snapshots")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise EvidenceCollectionError("input must be a JSON object")
        repository = payload.get("repository", "CarAutopsy/carautopsy")
        tasks, issues = payload.get("roadmap_tasks"), payload.get("issue_snapshots")
        if not isinstance(tasks, list) or not isinstance(issues, list):
            raise EvidenceCollectionError("input requires roadmap_tasks and issue_snapshots arrays")
        projected = []
        for item in issues:
            if not isinstance(item, dict):
                raise EvidenceCollectionError("issue snapshots must be objects")
            projected.append({key: item[key] for key in ("number", "state", "updated_at") if key in item})
        evidence = collect_github_evidence(repository, projected, token=os.environ.get("GITHUB_TOKEN"))
        report = build_reconciliation_proposal(tasks, projected, evidence["pull_request_evidence"], evidence["check_runs"], repository=repository)
        report.update({"repository": repository, "source": "github-live-evidence",
                       "issue_snapshots_seen": len(projected), "roadmap_modified": False,
                       "github_modified": False, "task_dispatch_performed": False})
        sys.stdout.write(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, EvidenceCollectionError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
