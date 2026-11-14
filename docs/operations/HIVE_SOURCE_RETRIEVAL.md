# Hive source retrieval: security boundary and integration contract

**Status:** source policy, retrieval, extraction, evidence, candidate validation, and pipeline orchestration are implemented on `main`; production retrieval remains deliberately disabled pending owner review, AI cross-review, owner-reviewed sources, exact-head validation, and explicit owner authorization.

## Fail-closed policy

`data-connectors/approved-source-hosts.json` is the owner-controlled source manifest. `approved_hosts` contains exact lowercase hostnames only; each `source_policies` entry binds one host to exact HTTPS `approved_urls` records, each scoped to explicit `variant_ids`, and reviewed terms metadata. Both arrays are intentionally empty. Do not add domains or URLs automatically from candidate data. A hostname and each exact source URL may be added only after owner review confirms source relevance and automated-access terms. Wildcards, host patterns, ports and candidate-controlled allowlists are forbidden.

`scripts/hive_source_policy.py` loads owner-reviewed exact host and exact URL entries from the manifest. Each source entry requires `automated_access_allowed: true`, a terms URL, a terms review date no older than 180 days, a reviewer identity, and a review reference. The exact source URL must be listed; candidate data cannot add hosts or paths. Before fetching the source, the policy checker retrieves `/robots.txt` through the same DNS-pinned HTTPS transport and applies the rules for `CarAutopsy-Research-Bot`. Robots directives use the longest matching path rule; `Allow` wins ties. The matcher supports `*` wildcards and terminal `$` anchors, normalizes percent-encoded unreserved octets, and uses bounded-time matching rather than regular-expression backtracking. Missing, unavailable, malformed, stale, ambiguous, or denying policy results fail closed. The low-level `fetch_source()` transport accepts no robots-policy callback and performs no policy evaluation. The evidence adapter invokes this policy check before the target fetch; the `/robots.txt` bootstrap request is used only to evaluate policy and never authorizes the target document by itself.

## Network controls

- HTTPS only; reject credentials, IP-literal URLs, non-standard ports, malformed URLs and control characters.
- Exact hostname match against the review-controlled allowlist.
- Resolve every A/AAAA answer and reject the hostname if any answer is not globally routable.
- Connect only to DNS answers that have all passed public-address validation. Give each remaining validated address a bounded share of the remaining connection-setup budget, so a blackholed address cannot consume the entire request deadline. If TCP setup or a non-identity TLS handshake fails before any HTTP request, try the next validated address in resolver order. Certificate/hostname verification failures are terminal and never trigger address fallback. Once connected, HTTP I/O resumes under the original absolute retrieval deadline; the total deadline is never extended. TLS SNI and certificate hostname verification always use the original hostname; no request is sent until one address completes connection setup.
- No environment proxy, automatic redirect, or second DNS resolution is used by the pinned connection.
- Reject all redirects in this first implementation; no redirect target is ever requested.
- Redirect responses are detected after the first successful TLS connection and are never followed. The transport issues exactly one HTTP request for an approved target URL; a 301, 302, 307, or 308 response returns `redirect_not_followed` without issuing a second request or opening another connection.
- Identify the crawler with a project-owned GitHub repository URL; do not embed a maintainer personal email in outbound headers.
- Bound timeout to 30 seconds maximum and response bytes to 2 MB maximum; enforce both declared and streamed sizes.
- Accept only HTML, plain text and PDF content types. The extraction layer must never treat binary PDF bytes as prompt text.
- Reject known placeholder KBA numeric filenames and all-zero configurator identifiers.

## Evidence semantics

A successful HTTP response is recorded as `retrieved_unverified`. This means only that bytes were fetched from an allowed endpoint. It does not establish that the source supports any candidate claim. The returned response body is transient; `safe_record()` excludes it from durable diagnostics. Candidate provenance and claim-level support must still pass the deterministic candidate gate and two independent vendor audits.

The deterministic claim-evidence gate proves that each required claim is bound to a quote and locator present in the supplied source text. It does **not** independently prove that the quote is semantically relevant or factually supports the claim. The two independent vendor auditors assess candidate-level semantic support; the owner-led security review and five-service AI cross-review assess the retrieval system's security and residual risks. These review layers serve different purposes.

## Integrated but disabled

The following components are wired into the research-only path in `scripts/autonomous_pipeline.py`:

- `scripts/hive_source_policy.py`: owner-reviewed exact URL and terms metadata checks plus live robots.txt policy evaluation.
- `scripts/hive_source_retrieval.py`: callback-free HTTPS-only DNS-pinned transport, redirect rejection, public-address checks, bounded response/time limits, and safe retrieval metadata. It is a transport primitive, not a policy authorization; production target fetches must pass through `hive_evidence.py` after the owner-controlled robots/terms precheck.
- `scripts/hive_source_extract.py`: visible HTML text, strict UTF-8 plain text, and page-bounded PDF extraction. HTML and PDF parsing use OS-resource-limited workers (512 MiB address-space ceilings, 5-second CPU limit, 6.5-second parent timeout, bounded input/output, and minimal environments without provider credentials). The worker does not establish a separate network namespace; its parser path must remain free of network access.
- `scripts/hive_evidence.py`: exact URL/variant-scoped evidence retrieval, policy preflight, stable source IDs, bounded evidence output, and structured per-document/page locator text. Raw response bytes are not returned or persisted.
- `scripts/hive_candidate.py` and `scripts/hive_prompts.py`: schema, reserved identity, evidence, claim-quote/locator, prompt-injection-boundary, and exact verdict validation.
- `scripts/hive_orchestration.py`: preflight and cache evidence before proposal checkout/state overlay; require two independent auditor vendors to return exact standalone PASS tokens.

The production path remains unreachable because `VERIFIED_RETRIEVAL_AVAILABLE = False` and the research pause remains active. The owner-approved source manifest is empty. Do not enable paid research or live retrieval until the owner review, five-service AI cross-review, source review, exact-head validation, and explicit owner authorization are complete.

## Tests and limits

`tests/test_hive_source_retrieval.py` covers invalid schemes and hosts, empty allowlist, credentials, ports, IP literals, placeholders, private and mixed DNS answers, DNS failure, redirects, content types, declared and streamed size limits, rejection of caller-supplied policy callbacks, bounded DNS/transport timeouts, safe diagnostics, and the pinned-IP/original-host TLS seam. Evidence-adapter and subprocess tests separately prove that the owner-controlled robots precheck occurs before target retrieval and that denial stops the pipeline before mutation or provider calls. Other Hive tests cover source-policy parsing, extraction limits, candidate/evidence validation, orchestration ordering, and failure/recovery state invariants.

Tests use mocks, synthetic documents, and local repositories. They do not establish OEM source permission, source authenticity, factual claim support, or production readiness. Exact-head CI/security validation and the owner-led review process remain mandatory.
