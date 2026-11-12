# Hive source retrieval: security boundary and integration contract

**Status:** source policy, retrieval, extraction, evidence, candidate validation, and pipeline orchestration are implemented on `main`; production retrieval remains deliberately disabled pending independent audits, owner-reviewed sources, and explicit owner authorization.

## Fail-closed policy

`data-connectors/approved-source-hosts.json` is the owner-controlled source manifest. `approved_hosts` contains exact lowercase hostnames only; each `source_policies` entry binds one host to exact HTTPS `approved_urls` records, each scoped to explicit `variant_ids`, and reviewed terms metadata. Both arrays are intentionally empty. Do not add domains or URLs automatically from candidate data. A hostname and each exact source URL may be added only after owner review confirms source relevance and automated-access terms. Wildcards, host patterns, ports and candidate-controlled allowlists are forbidden.

`scripts/hive_source_policy.py` loads owner-reviewed exact host and exact URL entries from the manifest. Each source entry requires `automated_access_allowed: true`, a terms URL, a terms review date no older than 180 days, a reviewer identity, and a review reference. The exact source URL must be listed; candidate data cannot add hosts or paths. Before fetching the source, the policy checker retrieves `/robots.txt` through the same DNS-pinned HTTPS transport and applies the rules for `CarAutopsy-Research-Bot`. Robots directives use the longest matching path rule; `Allow` wins ties. The matcher supports `*` wildcards and terminal `$` anchors, normalizes percent-encoded unreserved octets, and uses bounded-time matching rather than regular-expression backtracking. Missing, unavailable, malformed, stale, ambiguous, or denying policy results fail closed. The low-level `fetch_source()` callback remains mandatory as a second guard. The `/robots.txt` bootstrap exception authorizes only that exact path; it never authorizes the target document.

## Network controls

- HTTPS only; reject credentials, IP-literal URLs, non-standard ports, malformed URLs and control characters.
- Exact hostname match against the review-controlled allowlist.
- Resolve every A/AAAA answer and reject the hostname if any answer is not globally routable.
- Connect the TCP socket to the selected validated IP. TLS SNI and certificate hostname verification continue to use the original hostname.
- No environment proxy, automatic redirect, or second DNS resolution is used by the pinned connection.
- Reject all redirects in this first implementation; no redirect target is ever requested.
- Identify the crawler with a project-owned GitHub repository URL; do not embed a maintainer personal email in outbound headers.
- Bound timeout to 30 seconds maximum and response bytes to 2 MB maximum; enforce both declared and streamed sizes.
- Accept only HTML, plain text and PDF content types. The extraction layer must never treat binary PDF bytes as prompt text.
- Reject known placeholder KBA numeric filenames and all-zero configurator identifiers.

## Evidence semantics

A successful HTTP response is recorded as `retrieved_unverified`. This means only that bytes were fetched from an allowed endpoint. It does not establish that the source supports any candidate claim. The returned response body is transient; `safe_record()` excludes it from durable diagnostics. Candidate provenance and claim-level support must still pass the deterministic candidate gate and two independent vendor audits.

The deterministic claim-evidence gate proves that each required claim is bound to a quote and locator present in the supplied source text. It does **not** independently prove that the quote is semantically relevant or factually supports the claim. Independent auditors must assess that question, and the required external security review remains outstanding.

## Integrated but disabled

The following components are wired into the research-only path in `scripts/autonomous_pipeline.py`:

- `scripts/hive_source_policy.py`: owner-reviewed exact URL and terms metadata checks plus live robots.txt policy evaluation.
- `scripts/hive_source_retrieval.py`: HTTPS-only DNS-pinned transport, redirect rejection, public-address checks, bounded response/time limits, and safe retrieval metadata.
- `scripts/hive_source_extract.py`: visible HTML text, strict UTF-8 plain text, and page-bounded PDF extraction. HTML and PDF parsing use OS-resource-limited workers (512 MiB address-space ceilings, 5-second CPU limit, 6.5-second parent timeout, bounded input/output, and minimal environments without provider credentials). The worker does not establish a separate network namespace; its parser path must remain free of network access.
- `scripts/hive_evidence.py`: exact URL/variant-scoped evidence retrieval, policy preflight, stable source IDs, bounded evidence output, and structured per-document/page locator text. Raw response bytes are not returned or persisted.
- `scripts/hive_candidate.py` and `scripts/hive_prompts.py`: schema, reserved identity, evidence, claim-quote/locator, prompt-injection-boundary, and exact verdict validation.
- `scripts/hive_orchestration.py`: preflight and cache evidence before proposal checkout/state overlay; require two independent auditor vendors to return exact standalone PASS tokens.

The production path remains unreachable because `VERIFIED_RETRIEVAL_AVAILABLE = False` and the research pause remains active. The owner-approved source manifest is empty. Do not enable paid research or live retrieval until the independent audits, owner source review, exact-head validation, and explicit owner authorization are complete.

## Tests and limits

`tests/test_hive_source_retrieval.py` covers invalid schemes and hosts, empty allowlist, credentials, ports, IP literals, placeholders, private and mixed DNS answers, DNS failure, redirects, content types, declared and streamed size limits, required robots policy, bounded timeout, safe diagnostics, and the pinned-IP/original-host TLS seam. Other Hive tests cover source-policy parsing, extraction limits, candidate/evidence validation, orchestration ordering, and failure/recovery state invariants.

Tests use mocks, synthetic documents, and local repositories. They do not establish live OEM permission, source authenticity, factual claim support, or production readiness. Full exact-head CI/security validation and independent external review remain mandatory.
