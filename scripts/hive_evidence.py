"""Owner-seeded retrieval adapter producing bounded prompt evidence bundles."""
from __future__ import annotations

import hashlib
from urllib.parse import urlsplit
from datetime import date
from pathlib import Path
from typing import Callable

try:  # Support both script execution and package imports in unit tests.
    from .hive_source_extract import ExtractionRejected, extract_source_text
    from .hive_source_policy import SourcePolicyDenied, check_source_access, load_policy
    from .hive_source_retrieval import fetch_source
    from .hive_candidate import validate_evidence_bundle
except ImportError:  # pragma: no cover - exercised by the script entry point.
    from hive_source_extract import ExtractionRejected, extract_source_text
    from hive_source_policy import SourcePolicyDenied, check_source_access, load_policy
    from hive_source_retrieval import fetch_source
    from hive_candidate import validate_evidence_bundle


class EvidenceRetrievalRejected(ValueError):
    """Raised when approved source retrieval cannot produce a safe evidence bundle."""


def retrieve_approved_evidence(
    *,
    variant_id: str,
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
    if not isinstance(variant_id, str) or not variant_id.strip():
        raise EvidenceRetrievalRejected("reserved variant ID is required")
    hosts = config.get("approved_hosts")
    policies = config.get("source_policies")
    if not isinstance(hosts, list) or not hosts or not isinstance(policies, list) or not policies:
        raise EvidenceRetrievalRejected("no owner-approved source URLs are configured")

    seeded_sources = []
    for entry in policies:
        if not isinstance(entry, dict):
            raise EvidenceRetrievalRejected("source policy entry is malformed")
        approved_sources = entry.get("approved_urls")
        if not isinstance(approved_sources, list) or not approved_sources:
            raise EvidenceRetrievalRejected("source policy entry has no owner-approved URLs")
        for source in approved_sources:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str):
                raise EvidenceRetrievalRejected("approved source entry is malformed")
            variant_ids = source.get("variant_ids")
            if not isinstance(variant_ids, list) or not variant_ids:
                raise EvidenceRetrievalRejected("approved source entry has no variant scope")
            try:
                source_host = (urlsplit(source["url"]).hostname or "").rstrip(".").lower()
            except ValueError as exc:
                raise EvidenceRetrievalRejected("approved source URL is malformed") from exc
            entry_host = entry.get("host")
            if not isinstance(entry_host, str) or source_host != entry_host.rstrip(".").lower():
                raise EvidenceRetrievalRejected("approved source URL host does not match its policy entry")
            if variant_id in variant_ids:
                seeded_sources.append((entry, source["url"]))
    if not seeded_sources:
        raise EvidenceRetrievalRejected("no exact source URLs are approved for this variant")
    seeded_urls = [url for _, url in seeded_sources]
    if len(seeded_urls) > 10:
        raise EvidenceRetrievalRejected("owner-approved source list exceeds the ten-source limit")
    if len(set(seeded_urls)) != len(seeded_urls):
        raise EvidenceRetrievalRejected("duplicate owner-approved source URL")

    evidence = []
    total_chars = 0
    for entry, url in seeded_sources:
            # The production fetcher converts expected transport/policy rejections
            # into a rejected RetrievalResult, while the robots check raises the
            # explicit SourcePolicyDenied type. Do not catch arbitrary exceptions
            # here: programming errors and broken injected fetchers must fail red.
            check_source_access(url, config=config, fetcher=fetcher, today=today)
            result = fetcher(
                url,
                approved_hosts=hosts,
                robots_allowed=lambda requested: requested == url,
            )
            if getattr(result, "outcome", None) != "retrieved_unverified":
                raise EvidenceRetrievalRejected("approved source was not retrieved successfully")
            body = getattr(result, "body", None)
            content_type = getattr(result, "content_type", None)
            retrieved_at = getattr(result, "retrieved_at", None)
            if not isinstance(body, bytes) or not isinstance(retrieved_at, str) or not retrieved_at:
                raise EvidenceRetrievalRejected("retrieval result lacks transient body or timestamp")
            try:
                # Reserve space for the generated document locator marker so the
                # final serialized excerpt never exceeds the shared 20k ceiling.
                extracted = extractor(body, content_type, max_chars=19_989)
            except ExtractionRejected as exc:
                raise EvidenceRetrievalRejected("source extraction failed closed") from exc
            text = extracted.text
            if tuple(getattr(extracted, "locators", ())) == ("document",):
                text = "[document]\n" + text
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
                "locator_texts": dict(extracted.locator_texts),
            })

    try:
        return validate_evidence_bundle(evidence)
    except ValueError as exc:
        raise EvidenceRetrievalRejected("retrieved evidence bundle failed deterministic bounds") from exc
