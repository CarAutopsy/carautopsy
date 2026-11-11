"""Selection helpers for the autonomous Hive research pull request."""


def select_open_research_pr(pull_requests, repository_full_name):
    """Select one open same-repository Hive PR, rejecting ambiguous state."""
    matches = [
        pr for pr in pull_requests
        if (pr.get("headRefName") or "").startswith("hive/research-")
        and (pr.get("headRepository") or {}).get("nameWithOwner") == repository_full_name
    ]
    if len(matches) > 1:
        numbers = [pr.get("number") for pr in matches]
        raise RuntimeError(f"multiple open Hive research PRs found: {numbers}")
    return matches[0] if matches else None
