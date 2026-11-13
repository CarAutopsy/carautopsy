# Hive security review record template

**Project:** `CarAutopsy/carautopsy`  
**Issue:** [#37 — Hive retrieval/provenance security](https://github.com/CarAutopsy/carautopsy/issues/37)  
**Operating model:** one-person, zero-budget hobby project  
**Prepared:** 2026-11-13

## 1. Review model

The project owner is the sole human maintainer and performs the required human security review. No paid external auditor is required or budgeted.

The owner uses the five AI services already in the project as supplementary cross-reviewers. AI findings are not represented as independent human certification. The owner remains responsible for reading the implementation, evaluating each finding, documenting disagreements, and issuing the final human verdict.

Record the five service names and exact model/version identifiers actually used at review time; do not infer or invent a list of completed reviews. For each service, preserve the prompt/scope, reviewed SHA (or state that it could not verify the SHA), findings, disagreements, and unresolved limitations. An unavailable service or uncompleted review must be marked pending, not passed.

## 2. Exact review target

- Repository: `CarAutopsy/carautopsy`
- Branch/ref: `main`
- Exact audited commit SHA: **REQUIRED**
- Review date (UTC): **REQUIRED**
- Owner/auditor: project owner
- Relevant PRs and files: list exact PRs/files inspected.

Do not silently mix findings from different revisions. If `main` advances during review, either finish against the pinned SHA or record a new exact SHA and repeat affected checks.

## 3. System boundary and stop conditions

Hive research is integrated but deliberately disabled:

- `VERIFIED_RETRIEVAL_AVAILABLE = False`.
- `HIVE_RESEARCH_PAUSED` remains active.
- `data-connectors/approved-source-hosts.json` has empty `approved_hosts` and `source_policies` arrays.
- No live OEM retrieval, paid provider calls, or vehicle research dispatch is authorized.

Use static review, local unit tests, synthetic documents, and controlled local fixtures. Do not enable retrieval, add source hosts/URLs, remove the pause, dispatch research, access OEM endpoints, or make paid provider calls as part of this review. Those actions require a separate explicit owner authorization after all acceptance criteria are met.

## 4. Review scope and security questions

Review the exact audited SHA, trace reachable call paths, and record files/lines and evidence. Treat candidate JSON, source URLs, fetched HTML/text/PDF, provider responses, and persisted state as untrusted.

### A. Destination control, SSRF, and DNS pinning

- HTTPS only; malformed URLs, credentials, IP literals, control characters, non-standard ports and unsafe schemes rejected.
- Candidate data cannot choose or broaden approved hostname/path/URL scope.
- Every A/AAAA answer validated; private, loopback, link-local, metadata, mixed, reserved or otherwise unsafe answers denied.
- The validated IP is the actual TCP destination; no second resolver path.
- Original hostname retained for TLS SNI and certificate verification.
- No proxy, browser, redirect or alternate transport bypass.
- Connection, read, total-time, response-size and content-type bounds enforced.
- URL parsing/normalization resists user-info, suffix, encoding and parser-differential bypasses.

### B. Owner source approval, robots, and terms

- Empty, missing, malformed, stale, ambiguous or unreadable policy fails closed.
- Exact owner-reviewed host and HTTPS URL scope enforced; no wildcards or candidate expansion.
- Owner approval metadata and freshness enforced.
- Robots policy retrieved via the same protected transport before target document fetch.
- Missing, unavailable, malformed, denying or exceptional robots results deny retrieval.
- Bootstrap exception permits only the exact robots path.
- Robots matching, normalization, wildcard/anchor and Allow/Disallow precedence behave as specified.
- Terms metadata is an owner-reviewed attestation, not an automated legal determination.

### C. Extraction, parser safety, and prompt injection

- Only supported HTML, plain-text and PDF types accepted.
- Input bytes, pages, extracted characters, parse duration and worker resources bounded.
- Malformed, encrypted, oversized or unsupported documents fail safely.
- HTML/PDF extraction cannot trigger network access.
- Parser workers receive minimal environments without provider credentials or unnecessary secrets.
- Resource limits are not overstated as a complete OS sandbox or network namespace.
- Source text is untrusted data and cannot override system/developer instructions.
- Raw bodies, secrets and arbitrary untrusted page text are not persisted in retry ledgers or diagnostics.

### D. Evidence and candidate integrity

- Evidence bound to exact approved URLs and reserved variant IDs.
- Source IDs, canonical URLs, timestamps, content types, locators, quote spans and excerpt sizes validated.
- Required non-null technical claims have bounded source/quote/locator support.
- Mismatched URLs/variants, fabricated IDs, missing evidence, unsupported claims and malformed data fail closed.
- Quote presence is not mistaken for semantic relevance or factual support.
- HTTP 2xx and `retrieved_unverified` are never correctness proof.

### E. Pipeline ordering and zero bypass

- Readiness gate checked before research activity.
- Owner policy and evidence preflight precede proposal checkout, state overlay, and durable mutation.
- Deterministic candidate/schema/identity/evidence validation precedes both research-auditor calls.
- Rejected candidates trigger zero auditor calls.
- Both independent vendor auditors receive the same bounded validated candidate/evidence bundle.
- The two independent vendor PASS requirement cannot be bypassed by malformed verdicts, retries, fallback, exceptions or partial responses.
- Failed candidates cannot be promoted through retry, restart, proposal recovery or cross-process reconciliation.
- Failures leave queue/proposal/ledger/acknowledged state unchanged where required.
- The hard-disabled readiness flag and pause cannot be changed by candidate data, provider output, or ordinary task/PR paths.

### F. Operations and supply chain

Assess dependency/parser risks, secrets, logging, exception handling, test realism, CI/workflow permissions, and any diagnostic path that could invoke retrieval outside the readiness gate. Separate repository controls from deployment-level assumptions.

## 5. AI cross-review evidence

Complete one subsection per AI service actually used. Repeat rows as needed.

| Service | Model/version | Exact SHA verified? | Scope/prompt reference | Findings | Disagreements / unresolved risks |
|---|---|---|---|---|---|
| Service 1 | REQUIRED | Yes/No | REQUIRED | REQUIRED | REQUIRED |
| Service 2 | REQUIRED | Yes/No | REQUIRED | REQUIRED | REQUIRED |
| Service 3 | REQUIRED | Yes/No | REQUIRED | REQUIRED | REQUIRED |
| Service 4 | REQUIRED | Yes/No | REQUIRED | REQUIRED | REQUIRED |
| Service 5 | REQUIRED | Yes/No | REQUIRED | REQUIRED | REQUIRED |

Do not fill a row with an assumed result. Record service outage, rate limit, refusal, incomplete output, or an inability to confirm the reviewed SHA as a limitation.

## 6. Automated and manual test evidence

Record actual commands, runtime/tool versions, exact SHA, test result, and relevant run URLs.

- Python unit suite:
- Catalog validation:
- Recursive compilation:
- Repository Audit:
- Exact-head workflow checks:
- Targeted retrieval security regressions:
- Manual code-path/transport trace:
- Additional tests and limitations:

Mocked and synthetic tests do not prove OEM permission, source authenticity, factual claim support or production readiness. A pinned-transport test must be checked at the actual connection seam. Quote/locator validation proves traceability, not semantic relevance or truth. Parser resource limits do not prove full OS/network isolation.

## 7. Findings register

For each finding record unique ID, severity (Critical/High/Medium/Low/Informational), file/line at exact SHA, preconditions, attack/failure scenario, impact, reproduction evidence, remediation, and disposition. Record disagreements between owner analysis and each AI service explicitly. Track unresolved risks and residual limitations even when no code change is required.

## 8. Owner verdict

- Exact audited SHA:
- Verdict: **PASS / PASS WITH CONDITIONS / FAIL**
- Findings disposition:
- Outstanding conditions:
- Five AI cross-reviews completed:
- Unresolved disagreements/risks:
- Residual limitations:
- CI/test evidence:
- Confirmed no live provider calls, OEM retrieval, or factual vehicle-data verification:
- Confirmed no manifest, queue, ledger, branch, or production-state mutation:
- Owner authorization status (separate from verdict):

A PASS must not be issued while a Critical or High finding remains unresolved. A conditional verdict must list objective closure conditions. The owner records the final human decision and rationale; AI services do not vote or substitute for the owner.

## 9. Acceptance and activation boundary

Issue #37 may be considered review-complete only after the owner has recorded the exact-SHA human review, the five-service cross-review results/disagreements/limitations, finding dispositions, and exact-head automated validation.

Even then, review completion is **not** activation permission. The source manifest remains empty, `VERIFIED_RETRIEVAL_AVAILABLE = False`, and `HIVE_RESEARCH_PAUSED` remains active until the owner separately reviews proposed sources and explicitly authorizes activation.

This document is a review record template, not an audit result, certification, source-access permission, or activation approval.
