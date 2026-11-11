"""Owner-seeded retrieval adapter producing bounded prompt evidence bundles."""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Callable

try:  # Support both script execution and package imports in unit tests.
    from .hive_source_extract import extract_source_text
    from .hive_source_policy import SourcePolicyDenied, check_source_access, load_policy
    from .hive_source_retrieval import fetch_source
    from .hive_candidate import validate_evidence_bundle
except ImportError:  # pragma: no cover - exercised by the script entry point.
    from hive_source_extract import extract_source_text
    from hive_source_policy import SourcePolicyDenied, check_source_access, load_policy
    from hive_source_retrieval import fetch_source
    from hive_candidate import validate_evidence_bundle


class EvidenceRetrievalRejected(ValueError):
    """Raised when approved source retrieval cannot produce a safe evidence bundle."""


def retrieve_approved_evidence(
    *,
    config_path: Path | None = None,
    config: dict | None = None,
    fetcher: Callable = fetch_source,
    extractor: Callable = extract_source_text,
    today: date | None = None,
) -> list[dict[str, str]]:
    """Fetch only owner-listed exact URLs and return bounded text, never raw bytes.

    Candidate/provider output is not accepted as a source URL input. Source URLs come
    exclusively from the owner-controlled source policy manifest.
    """
    if config is None:
        config = load_policy(config_path) if config_path is not None else load_policy()
    if not isinstance(config, dict):
        raise EvidenceRetrievalRejected("source policy configuration is invalid")
    hosts = config.get("approved_hosts")
    policies = config.get("source_policies")
    if not isinstance(hosts, list) or not hosts or not isinstance(policies, list) or not policies:
        raise EvidenceRetrievalRejected("no owner-approved source URLs are configured")

    seeded_urls = []
    for entry in policies:
        if not isinstance(entry, dict):
            raise EvidenceRetrievalRejected("source policy entry is malformed")
        urls = entry.get("approved_urls")
        if not isinstance(urls, list) or not urls:
            raise EvidenceRetrievalRejected("source policy entry has no owner-approved URLs")
        seeded_urls.extend(urls)
    if len(seeded_urls) > 10:
        raise EvidenceRetrievalRejected("owner-approved source list exceeds the ten-source limit")
    if any(not isinstance(url, str) for url in seeded_urls) or len(set(seeded_urls)) != len(seeded_urls):
        raise EvidenceRetrievalRejected("duplicate or invalid owner-approved source URL")

    evidence = []
    total_chars = 0
    for entry in policies:
        if not isinstance(entry, dict):
            raise EvidenceRetrievalRejected("source policy entry is malformed")
        urls = entry.get("approved_urls")
        if not isinstance(urls, list) or not urls:
            raise EvidenceRetrievalRejected("source policy entry has no owner-approved URLs")
        for url in urls:
            try:
                # Check owner terms and fetch/parse robots.txt before requesting the
                # source document. The second request uses the same pinned transport;
                # its callback is a one-use authorization from the immediately prior check.
                check_source_access(url, config=config, fetcher=fetcher, today=today)
                result = fetcher(
                    url,
                    approved_hosts=hosts,
                    robots_allowed=lambda requested: requested == url,
                )
            except Exception as exc:
                raise EvidenceRetrievalRejected("source retrieval failed closed") from exc
            if getattr(result, "outcome", None) != "retrieved_unverified":
                raise EvidenceRetrievalRejected("approved source was not retrieved successfully")
            body = getattr(result, "body", None)
            content_type = getattr(result, "content_type", None)
            retrieved_at = getattr(result, "retrieved_at", None)
            if not isinstance(body, bytes) or not isinstance(retrieved_at, str) or not retrieved_at:
                raise EvidenceRetrievalRejected("retrieval result lacks transient body or timestamp")
            try:
                extracted = extractor(body, content_type, max_chars=20_000)
            except Exception as exc:
                raise EvidenceRetrievalRejected("source extraction failed closed") from exc
            text = extracted.text
            if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
                raise EvidenceRetrievalRejected("extracted source text is empty or exceeds the excerpt limit")
            total_chars += len(text)
            if total_chars > 60_000 or len(evidence) >= 10:
                raise EvidenceRetrievalRejected("evidence bundle exceeds source or character limits")
            source_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
            evidence.append({
                "source_id": source_id,
                "url": url,
                "retrieved_at": retrieved_at,
                "text": text,
            })

    try:
        return validate_evidence_bundle(evidence)
    except ValueError as exc:
        raise EvidenceRetrievalRejected("retrieved evidence bundle failed deterministic bounds") from exc
