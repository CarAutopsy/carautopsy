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


def _normalize_robots_octets(value: str) -> str:
    """Decode percent-encoded unreserved ASCII octets; preserve reserved escapes."""
    unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"

    def replace(match: re.Match[str]) -> str:
        octet = int(match.group(1), 16)
        char = chr(octet)
        return char if char in unreserved else f"%{octet:02X}"

    return re.sub(r"%([0-9A-Fa-f]{2})", replace, value)


def _robots_glob_matches(pattern: str, value: str, *, terminal: bool) -> bool:
    """Match '*' with a linear greedy glob algorithm, never a backtracking regex."""
    pattern_index = value_index = 0
    last_star = -1
    star_value_index = 0
    while value_index < len(value):
        if pattern_index < len(pattern) and pattern[pattern_index] != "*" and pattern[pattern_index] == value[value_index]:
            pattern_index += 1
            value_index += 1
        elif pattern_index < len(pattern) and pattern[pattern_index] == "*":
            last_star = pattern_index
            pattern_index += 1
            star_value_index = value_index
        elif last_star >= 0:
            star_value_index += 1
            value_index = star_value_index
            pattern_index = last_star + 1
        else:
            return False
        if not terminal and pattern_index == len(pattern):
            return True
    while pattern_index < len(pattern) and pattern[pattern_index] == "*":
        pattern_index += 1
    return pattern_index == len(pattern)


def _robots_can_fetch(text: str, user_agent: str, url: str) -> bool:
    """Evaluate bounded RFC 9309-style longest-match rules; malformed directives deny."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    saw_rule = False
    directive_count = 0

    def finish_group() -> None:
        nonlocal agents, rules, saw_rule
        if agents:
            groups.append((agents, rules))
        agents, rules, saw_rule = [], [], False

    for raw_line in text.splitlines():
        if len(raw_line) > 2048:
            raise SourcePolicyDenied("robots.txt contains an overlong directive")
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        directive_count += 1
        if directive_count > 10_000:
            raise SourcePolicyDenied("robots.txt contains too many directives")
        if ":" not in line:
            raise SourcePolicyDenied("robots.txt contains a malformed directive")
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not re.fullmatch(r"(?:\*|[A-Za-z_-]+)", value, flags=re.ASCII):
                raise SourcePolicyDenied("robots.txt contains an invalid user-agent")
            if saw_rule:
                finish_group()
            agents.append(value.lower())
        elif key in ("allow", "disallow"):
            if not agents:
                raise SourcePolicyDenied("robots.txt rule appears before a user-agent group")
            if value and not value.startswith("/") and not value.startswith("*"):
                raise SourcePolicyDenied("robots.txt contains an invalid path rule")
            if len(value) > 2048:
                raise SourcePolicyDenied("robots.txt contains an overlong path rule")
            rules.append((key, value))
            saw_rule = True
        elif key in ("sitemap", "crawl-delay", "request-rate", "host"):
            if not value:
                raise SourcePolicyDenied("robots.txt contains an empty extension directive")
        else:
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
    path_query = _normalize_robots_octets(parsed.path or "/")
    if parsed.query:
        path_query += "?" + _normalize_robots_octets(parsed.query)
    matches: list[tuple[int, str]] = []
    matching_work = 0
    for directive, raw_pattern in rules_to_apply:
        if not raw_pattern:
            continue
        terminal = raw_pattern.endswith("$")
        pattern = _normalize_robots_octets(raw_pattern[:-1] if terminal else raw_pattern)
        matching_work += len(pattern) * len(path_query)
        if matching_work > 2_000_000:
            raise SourcePolicyDenied("robots.txt matching complexity exceeds the safe work budget")
        if _robots_glob_matches(pattern, path_query, terminal=terminal):
            specificity = len(pattern.replace("*", "").encode("utf-8"))
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
    approved-host, pinned-IP, HTTPS-only, no-redirect transport. The target document
    must not be fetched until this function returns successfully.
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
    # Fetch only the robots bootstrap document. No policy callback is passed to
    # the transport; the parsed rules below decide whether the target URL is allowed.
    result = fetcher(robots_url, approved_hosts=config["approved_hosts"])
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


def require_variant_coverage(config: dict, variant_ids: list[str], today: date | None = None) -> None:
    """Preflight owner policy coverage before any proposal checkout or state access."""
    if not isinstance(config, dict):
        raise SourcePolicyDenied("source policy configuration is invalid")
    hosts = config.get("approved_hosts")
    entries = config.get("source_policies")
    if not isinstance(hosts, list) or not hosts or not isinstance(entries, list) or not entries:
        raise SourcePolicyDenied("owner-approved source manifest is empty")
    if not isinstance(variant_ids, list) or any(
        not isinstance(value, str) or not value.strip() for value in variant_ids
    ):
        raise SourcePolicyDenied("reserved variant batch is invalid")
    current_date = today or date.today()
    covered: set[str] = set()
    seen_hosts: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SourcePolicyDenied("source policy entry is malformed")
        host = entry.get("host")
        if not isinstance(host, str) or host not in hosts:
            raise SourcePolicyDenied("source policy entry host is not owner-approved")
        if host not in seen_hosts:
            _host_policy(config, host, current_date)
            seen_hosts.add(host)
        approved_urls = entry.get("approved_urls")
        if not isinstance(approved_urls, list) or not approved_urls:
            raise SourcePolicyDenied("owner-approved exact source URL list is missing")
        for source in approved_urls:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str):
                raise SourcePolicyDenied("approved source entry is malformed")
            try:
                parsed = urlsplit(source["url"])
                port = parsed.port
            except ValueError as exc:
                raise SourcePolicyDenied("approved source URL is malformed") from exc
            if (
                parsed.scheme != "https"
                or parsed.hostname != host
                or parsed.username is not None
                or parsed.password is not None
                or port not in (None, 443)
                or parsed.fragment
            ):
                raise SourcePolicyDenied("approved source URL does not match its exact HTTPS policy host")
            scopes = source.get("variant_ids")
            if not isinstance(scopes, list) or not scopes or any(
                not isinstance(value, str) or not value.strip() for value in scopes
            ):
                raise SourcePolicyDenied("approved source URL requires explicit variant scope")
            covered.update(scopes)
    missing = sorted(set(variant_ids) - covered)
    if missing:
        raise SourcePolicyDenied(
            "owner-approved source manifest does not cover the upcoming reserved batch"
        )
