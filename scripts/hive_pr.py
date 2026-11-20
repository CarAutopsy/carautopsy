"""Selection helpers for the autonomous Hive research pull request."""

# A full page at this ceiling is treated as an incomplete, unsafe result instead
# of doubling forever. This keeps duplicate-PR prevention from hanging or
# exhausting memory on a stuck/malformed GitHub response.
MAX_FETCH_LIMIT = 2000


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


def fetch_all_open_pull_requests(fetch_page, initial_limit=100):
    """Fetch every open PR by increasing gh's result limit until complete.

    Fails closed on malformed pages and on a result that stays full at the
    safety ceiling, so a stuck API response cannot loop indefinitely.
    """
    if isinstance(initial_limit, bool) or not isinstance(initial_limit, int) or initial_limit < 1 or initial_limit > MAX_FETCH_LIMIT:
        raise ValueError(f"initial_limit must be an integer in 1..{MAX_FETCH_LIMIT}")
    limit = initial_limit
    while True:
        pull_requests = fetch_page(limit)
        if not isinstance(pull_requests, list):
            raise RuntimeError("open PR page must be a list")
        if len(pull_requests) < limit:
            return pull_requests
        if limit >= MAX_FETCH_LIMIT:
            raise RuntimeError(f"open PR fetch exceeded the {MAX_FETCH_LIMIT} result bound")
        limit = min(limit * 2, MAX_FETCH_LIMIT)
