"""Owner-controlled, fail-closed robots.txt and source-terms policy checks."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "data-connectors" / "approved-source-hosts.json"
MAX_POLICY_AGE_DAYS = 180
USER_AGENT = "CarAutopsy-Research-Bot"


class SourcePolicyDenied(ValueError):
    """Raised when owner approval or robots policy cannot be established."""


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict:
    """Load and validate the owner-maintained policy; never infer hosts from candidates."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourcePolicyDenied("source policy configuration is unavailable or malformed") from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise SourcePolicyDenied("unsupported source policy configuration")
    hosts = value.get("approved_hosts")
    policies = value.get("source_policies")
    if not isinstance(hosts, list) or not isinstance(policies, list):
        raise SourcePolicyDenied("source policy must define approved_hosts and source_policies arrays")
    if not hosts:
        raise SourcePolicyDenied("approved-host allowlist is empty")
    if any(not isinstance(host, str) or not host or host != host.strip() or host != host.lower() for host in hosts):
        raise SourcePolicyDenied("approved host entries must be exact lowercase hostnames")
    if len(set(hosts)) != len(hosts):
        raise SourcePolicyDenied("duplicate approved host entry")
    return value


def _host_policy(config: dict, host: str, today: date) -> dict:
    entries = [item for item in config["source_policies"]
               if isinstance(item, dict) and item.get("host") == host]
    if len(entries) != 1:
        raise SourcePolicyDenied("exactly one owner-reviewed source-terms entry is required")
    item = entries[0]
    if host not in config["approved_hosts"]:
        raise SourcePolicyDenied("source hostname is not owner-approved")
    if item.get("automated_access_allowed") is not True:
        raise SourcePolicyDenied("owner-reviewed source terms do not permit automated access")
    approved_urls = item.get("approved_urls")
    if not isinstance(approved_urls, list) or not approved_urls or any(not isinstance(value, str) for value in approved_urls):
        raise SourcePolicyDenied("owner-reviewed exact source URL list is missing")
    terms_url = item.get("terms_url")
    review_ref = item.get("terms_review_ref")
    for label, value in (("source terms URL", terms_url), ("source terms review reference", review_ref)):
        if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 32 for char in value):
            raise SourcePolicyDenied(f"{label} is missing or invalid")
        try:
            parsed_link = urlsplit(value)
            port = parsed_link.port
        except ValueError as exc:
            raise SourcePolicyDenied(f"{label} is malformed") from exc
        if parsed_link.scheme != "https" or not parsed_link.hostname or parsed_link.username is not None or parsed_link.password is not None or port not in (None, 443):
            raise SourcePolicyDenied(f"{label} must be a valid HTTPS URL without credentials or a non-standard port")
    reviewer = item.get("terms_reviewed_by")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 128:
        raise SourcePolicyDenied("source terms reviewer identity is missing")
    reviewed = item.get("terms_reviewed_at")
    try:
        reviewed_date = date.fromisoformat(reviewed)
    except (TypeError, ValueError) as exc:
        raise SourcePolicyDenied("source terms review date is missing or invalid") from exc
    age = (today - reviewed_date).days
    if age < 0 or age > MAX_POLICY_AGE_DAYS:
        raise SourcePolicyDenied("source terms review is future-dated or stale")
    return item


def check_source_access(
    url: str,
    *,
    config: dict,
    fetcher,
    user_agent: str = USER_AGENT,
    today: date | None = None,
) -> bool:
    """Return True only when owner terms and live robots.txt permit this exact URL.

    The injected fetcher must be the project's DNS-pinned fetch_source implementation.
    The robots.txt request is the sole policy-bootstrap request and uses the same
    approved-host, pinned-IP, HTTPS-only, no-redirect transport.
    """
    if not isinstance(url, str) or len(url) > 2048:
        raise SourcePolicyDenied("source URL is missing or too long")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None:
        raise SourcePolicyDenied("source URL must be HTTPS with a hostname and no credentials")
    current_day = today or datetime.now(timezone.utc).date()
    policy_entry = _host_policy(config, host, current_day)
    if url not in policy_entry["approved_urls"]:
        raise SourcePolicyDenied("source URL is not in the owner-reviewed exact URL list")

    robots_url = urlunsplit(("https", host, "/robots.txt", "", ""))
    # This callback is intentionally limited to fetching robots.txt itself. It does
    # not authorize the target URL; the parsed robots policy below makes that decision.
    result = fetcher(
        robots_url,
        approved_hosts=config["approved_hosts"],
        robots_allowed=lambda requested: requested == robots_url,
    )
    if getattr(result, "outcome", None) != "retrieved_unverified" or not isinstance(getattr(result, "body", None), bytes):
        raise SourcePolicyDenied("robots.txt could not be retrieved safely")
    try:
        text = result.body.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise SourcePolicyDenied("robots.txt is not valid UTF-8") from exc
    if len(text) > 256_000:
        raise SourcePolicyDenied("robots.txt exceeds the policy size limit")
    lines = text.splitlines()
    if not any(line.lstrip().lower().startswith("user-agent:") for line in lines):
        raise SourcePolicyDenied("robots.txt is missing a valid user-agent directive")
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.parse(lines)
        permitted = parser.can_fetch(user_agent, url)
    except Exception as exc:
        raise SourcePolicyDenied("robots.txt policy could not be parsed") from exc
    if permitted is not True:
        raise SourcePolicyDenied("robots.txt disallows this exact source URL")
    return True
