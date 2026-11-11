"""Owner-controlled, fail-closed robots.txt and source-terms policy checks."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
    if not isinstance(approved_urls, list) or not approved_urls:
        raise SourcePolicyDenied("owner-reviewed exact source URL list is missing")
    approved_url_values = []
    for source in approved_urls:
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            raise SourcePolicyDenied("approved source entries must bind exact URLs to variant IDs")
        variant_ids = source.get("variant_ids")
        if not isinstance(variant_ids, list) or not variant_ids or any(not isinstance(value, str) or not value.strip() for value in variant_ids):
            raise SourcePolicyDenied("approved source entries require explicit variant IDs")
        approved_url_values.append(source["url"])
    if len(set(approved_url_values)) != len(approved_url_values):
        raise SourcePolicyDenied("duplicate exact source URL in owner policy")
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


def _robots_can_fetch(text: str, user_agent: str, url: str) -> bool:
    """Evaluate RFC 9309-style longest-match rules; malformed directives deny."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    saw_rule = False

    def finish_group() -> None:
        nonlocal agents, rules, saw_rule
        if agents:
            groups.append((agents, rules))
        agents, rules, saw_rule = [], [], False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise SourcePolicyDenied("robots.txt contains a malformed directive")
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not value or any(ch.isspace() for ch in value):
                raise SourcePolicyDenied("robots.txt contains an invalid user-agent")
            if saw_rule:
                finish_group()
            agents.append(value.lower())
        elif key in ("allow", "disallow"):
            if not agents:
                raise SourcePolicyDenied("robots.txt rule appears before a user-agent group")
            if value and not value.startswith("/") and not value.startswith("*"):
                raise SourcePolicyDenied("robots.txt contains an invalid path rule")
            rules.append((key, value))
            saw_rule = True
        elif key in ("sitemap", "crawl-delay", "request-rate", "host"):
            # These directives do not grant or deny a path. Validate their presence,
            # but do not use non-standard extensions to relax access decisions.
            if not value:
                raise SourcePolicyDenied("robots.txt contains an empty extension directive")
        else:
            # Unknown directives are ambiguous for this conservative crawler.
            raise SourcePolicyDenied("robots.txt contains an unsupported directive")
    finish_group()
    if not groups:
        raise SourcePolicyDenied("robots.txt is missing a valid user-agent group")

    agent = user_agent.lower()
    matching_specificity = -1
    selected_rules: list[tuple[str, str]] = []
    wildcard_rules: list[tuple[str, str]] = []
    for group_agents, group_rules in groups:
        for token in group_agents:
            if token == "*":
                wildcard_rules.extend(group_rules)
            elif token in agent and len(token) > matching_specificity:
                matching_specificity = len(token)
                selected_rules = list(group_rules)
            elif token in agent and len(token) == matching_specificity:
                selected_rules.extend(group_rules)
    rules_to_apply = selected_rules if matching_specificity >= 0 else wildcard_rules

    parsed = urlsplit(url)
    path_query = parsed.path or "/"
    if parsed.query:
        path_query += "?" + parsed.query
    matches: list[tuple[int, str]] = []
    for directive, pattern in rules_to_apply:
        if not pattern:
            continue
        terminal = pattern.endswith("$")
        expression = re.escape(pattern[:-1] if terminal else pattern).replace(r"\*", ".*")
        expression = "^" + expression + ("$" if terminal else "")
        if re.search(expression, path_query):
            specificity = len(pattern.rstrip("$").replace("*", ""))
            matches.append((specificity, directive))
    if not matches:
        return True
    longest = max(length for length, _ in matches)
    return any(directive == "allow" for length, directive in matches if length == longest)


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
    if url not in [source["url"] for source in policy_entry["approved_urls"]]:
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
    try:
        permitted = _robots_can_fetch(text, user_agent, url)
    except SourcePolicyDenied:
        raise
    except Exception as exc:
        raise SourcePolicyDenied("robots.txt policy could not be parsed") from exc
    if permitted is not True:
        raise SourcePolicyDenied("robots.txt disallows this exact source URL")
    return True
