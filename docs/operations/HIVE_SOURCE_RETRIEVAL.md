# Hive source retrieval: security boundary and integration contract

Status: retrieval primitive implemented; runtime integration and operational readiness are NOT complete.

## Fail-closed policy

`data-connectors/approved-source-hosts.json` is the owner-controlled exact-host allowlist. It is intentionally empty. Do not add domains automatically from candidate data. A hostname may be added only after an owner review confirms source relevance, automated-access terms and robots policy. Wildcards, URL paths, ports and candidate-controlled allowlists are forbidden.

`fetch_source()` requires both the explicit allowlist and a `robots_allowed(url)` policy callback. Missing callbacks, policy exceptions and denial all stop before DNS or network access. The callback must check robots.txt and source terms for the exact URL and must itself fail closed. The retrieval primitive does not pretend that an allowlisted host is permission to crawl it.

## Network controls

- HTTPS only; reject credentials, IP-literal URLs, non-standard ports, malformed URLs and control characters.
- Exact hostname match against the review-controlled allowlist.
- Resolve every A/AAAA answer and reject the hostname if any answer is not globally routable.
- Connect the TCP socket to the selected validated IP. TLS SNI and certificate hostname verification continue to use the original hostname.
- No environment proxy, automatic redirect, or second DNS resolution is used by the pinned connection.
- Reject all redirects in this first implementation; no redirect target is ever requested.
- Identify the crawler with a project-owned GitHub repository URL; do not embed a maintainer personal email in outbound headers.
- Bound timeout to 30 seconds maximum and response bytes to 2 MB maximum; enforce both declared and streamed sizes.
- Accept only HTML, plain text and PDF content types. The caller must extract text safely and must not treat binary PDF bytes as prompt text.
- Reject known placeholder KBA numeric filenames and all-zero configurator identifiers.

## Evidence semantics

A successful HTTP response is recorded as `retrieved_unverified`. This means only that bytes were fetched from an allowed endpoint. It does not establish that the source supports any candidate claim. The returned response body is transient; `safe_record()` excludes it from durable diagnostics. Candidate provenance and claim-level support must still pass the deterministic candidate gate and two independent vendor audits.

## Not enabled

This change does not wire retrieval into `autonomous_pipeline.py`, implement a production robots.txt fetcher, curate approved source domains, parse PDFs, or perform semantic claim verification. The allowlist remains empty and `VERIFIED_RETRIEVAL_AVAILABLE` must remain false. Do not enable paid research until those dependencies are implemented, reviewed and proven end to end.

## Tests

`tests/test_hive_source_retrieval.py` covers invalid schemes and hosts, empty allowlist, credentials, ports, IP literals, placeholders, private and mixed DNS answers, DNS failure, redirects, content types, declared and streamed size limits, required robots policy, bounded timeout, safe diagnostics, and the pinned-IP/original-host TLS seam. Tests use fakes and make no live requests.
