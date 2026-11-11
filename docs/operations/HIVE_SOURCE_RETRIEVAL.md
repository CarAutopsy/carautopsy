# Hive source retrieval: security boundary and integration contract

Status: retrieval primitive implemented; runtime integration and operational readiness are NOT complete.

## Fail-closed policy

`data-connectors/approved-source-hosts.json` is the owner-controlled source manifest. `approved_hosts` contains exact lowercase hostnames only; each `source_policies` entry binds one host to exact HTTPS `approved_urls` records, each scoped to explicit `variant_ids`, and reviewed terms metadata. Both arrays are intentionally empty. Do not add domains or URLs automatically from candidate data. A hostname and each exact source URL may be added only after owner review confirms source relevance and automated-access terms. Wildcards, host patterns, ports and candidate-controlled allowlists are forbidden.

`scripts/hive_source_policy.py` loads owner-reviewed exact host and exact URL entries from the manifest. Each source entry requires `automated_access_allowed: true`, a terms URL, a terms review date no older than 180 days, a reviewer identity, and a review reference. The exact source URL must be listed; candidate data cannot add hosts or paths. Before fetching the source, the policy checker retrieves `/robots.txt` through the same DNS-pinned HTTPS transport and applies the rules for `CarAutopsy-Research-Bot`. Missing, unavailable, malformed, stale, ambiguous, or denying policy results fail closed. The low-level `fetch_source()` callback remains mandatory as a second guard.

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

The new policy checker, evidence adapter, and bounded HTML/plain-text/PDF extractor are still isolated building blocks: they are not wired into `autonomous_pipeline.py`, do not curate approved source URLs, and do not perform semantic claim verification. PDF extraction runs in a separate worker with a 512 MiB address-space ceiling, a 5-second CPU limit, a 6.5-second parent timeout, bounded input/pages/text, and a minimal environment without provider credentials. The worker does not establish a separate network namespace; its parser path must remain free of network access. The manifest remains empty and `VERIFIED_RETRIEVAL_AVAILABLE` must remain false. Do not enable paid research until these dependencies are integrated, independently reviewed, and proven end to end.

## Tests

`tests/test_hive_source_retrieval.py` covers invalid schemes and hosts, empty allowlist, credentials, ports, IP literals, placeholders, private and mixed DNS answers, DNS failure, redirects, content types, declared and streamed size limits, required robots policy, bounded timeout, safe diagnostics, and the pinned-IP/original-host TLS seam. Tests use fakes and make no live requests.


## New isolated implementation building blocks

- `scripts/hive_source_policy.py`: owner-reviewed exact URL and terms metadata checks plus live robots.txt parsing.
- `scripts/hive_source_extract.py`: visible HTML text, strict UTF-8 plain text, and page-bounded PDF extraction in an OS-resource-limited worker (512 MiB address space, 5-second CPU limit, bounded wall time). Script/style/template/noscript/SVG/canvas/iframe/object content is excluded from HTML.
- `scripts/hive_evidence.py`: retrieves only exact URLs scoped to the reserved variant ID in the owner manifest, checks policy before the source request, extracts bounded text, assigns stable source IDs, and returns only the candidate gate's bounded evidence fields. Raw response bytes are not returned or persisted. PDF page markers and document locators remain adjacent to extracted text.
- `scripts/hive_candidate.py`: additionally requires every non-null technical, price, registration, and non-reserved identity claim to bind to an exact quoted source-text span and locator from a declared provenance source. This proves traceability to supplied text, not semantic relevance; independent auditors must still assess whether the quote supports the claim.
- Tests use mocked transport and synthetic documents only. They do not establish live OEM permission, source authenticity, factual claim support, or production readiness.
