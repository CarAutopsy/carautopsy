# Hive external security review brief

**Review target:** `CarAutopsy/carautopsy`  
**Target ref:** `main`  
**Exact target commit:** `71465beab90527e8a8788ab276cc42bba3383701`  
**Prepared:** 2026-11-12  
**Purpose:** Independent external security assessment for issue [#37](https://github.com/CarAutopsy/carautopsy/issues/37).

## 1. Independence and reviewer requirements

This review must be performed by a security reviewer independent of the implementation author and project owner. Before starting, the reviewer should disclose:

- Full name and professional role.
- Employer or organization (or state that the review is independent).
- Any financial, employment, advisory, personal, or other relationship with the project, repository owner, or implementers.
- Whether AI tools were used, which tools, and what work they performed.
- Relevant application-security, network-security, Python, SSRF, and document-parser experience.

A review by the repository owner, implementation author, this assistant, Qodo, CodeRabbit, Copilot, or another automated agent is useful supplementary evidence but does **not** satisfy the independent external review requirement.

Review the exact commit above. If `main` advances, either keep this SHA as the explicit review target or agree and record a new exact SHA before beginning. Do not silently mix findings from different revisions.

## 2. System purpose and security boundary

Hive research is intended to collect official, variant-scoped vehicle-source material, extract bounded evidence, validate candidate claims deterministically, and then submit the same validated bundle to two independent research auditors.

The system is integrated but deliberately disabled:

- `VERIFIED_RETRIEVAL_AVAILABLE = False`.
- `HIVE_RESEARCH_PAUSED` remains active.
- `data-connectors/approved-source-hosts.json` has empty `approved_hosts` and `source_policies` arrays.
- No live OEM retrieval, paid provider call, or vehicle research dispatch is authorized.
- The queue and failed-candidate ledger remain quarantined; no automatic retry or promotion is permitted while paused.

**The review must not enable retrieval, add source hosts/URLs, remove the pause, dispatch research, or make paid provider calls.** Use static analysis, local tests, synthetic documents, and controlled local fixtures. If a reviewer believes live testing is necessary, stop and request separate explicit owner authorization and a separately approved test plan.

## 3. Components in scope

Review these files at the target commit, plus their direct call sites and relevant tests:

### Source policy and retrieval
- `scripts/hive_source_policy.py`
- `scripts/hive_source_retrieval.py`
- `scripts/hive_evidence.py`
- `data-connectors/approved-source-hosts.json`

### Extraction and untrusted content handling
- `scripts/hive_source_extract.py`
- `scripts/hive_html_worker.py`
- `scripts/hive_pdf_worker.py`

### Candidate, evidence, and prompt validation
- `scripts/hive_candidate.py`
- `scripts/hive_prompts.py`
- `schemas/vehicle-variant.schema.json`

### Runtime ordering and recovery
- `scripts/hive_orchestration.py`
- `scripts/autonomous_pipeline.py`
- `scripts/hive_research_gate.py`
- Relevant queue, proposal, state, retry, and ledger call paths.

### Relevant test files
- `tests/test_hive_source_policy.py`
- `tests/test_hive_source_retrieval.py`
- `tests/test_hive_source_extract.py`
- `tests/test_hive_evidence.py`
- `tests/test_hive_candidate.py`
- `tests/test_hive_orchestration.py`
- All additional tests covering pipeline ordering, queue preflight, retry/restart, interruption, and cross-process state reconciliation.

The list is an entry point, not a restriction. Trace the full reachable call graph and inspect any additional security-relevant code or tests discovered.

## 4. Threat model and required review questions

Treat candidate JSON, source URLs, fetched HTML/text/PDF, extracted strings, provider responses, persisted state, and remote queue/proposal state as untrusted unless independently validated.

### A. Destination control, SSRF, and DNS pinning

Verify that:

1. Only HTTPS URLs are accepted; malformed URLs, credentials, IP literals, control characters, non-standard ports, and disallowed schemes are rejected.
2. A candidate cannot choose or broaden an approved hostname, path, or URL. The owner-controlled manifest is the only authority.
3. Every A/AAAA answer is checked and any non-public, mixed, private, loopback, link-local, multicast, reserved, or otherwise unsafe answer causes denial.
4. The validated public IP is the IP actually used for the TCP connection. There is no second DNS lookup or resolver path between validation and socket connection.
5. TLS SNI and certificate hostname verification use the original hostname, not the pinned IP.
6. Environment proxies, proxy variables, browser automation, redirects, alternate clients, and fallback transports cannot bypass the pinned connection.
7. Redirects are rejected, and no redirect target is requested.
8. Connection, read, total-time, response-size, and content-type limits are enforced on both declared and streamed data.
9. URL parsing and hostname normalization do not permit user-info, suffix, encoding, Unicode, trailing-dot, or parser-differential bypasses.

**Demand code-level evidence** for the actual socket dial and TLS identity. A unit test that only mocks DNS validation is not sufficient.

### B. Owner approval, robots.txt, and terms policy

Verify that:

1. Empty, missing, malformed, stale, ambiguous, or unreadable policy configuration fails closed.
2. Exact host and exact HTTPS URL scope is enforced, with no wildcard or candidate-controlled expansion.
3. Owner approval metadata is required and freshness is enforced.
4. Robots policy is retrieved through the same protected transport before target-document retrieval.
5. Missing, unavailable, malformed, denying, or exceptional robots results deny retrieval.
6. The robots bootstrap exception authorizes only the exact robots path, not the target document.
7. The selected user-agent, path matching, percent-encoding normalization, wildcard and end-anchor behavior, and Allow/Disallow precedence conform to the intended policy.
8. Terms metadata is treated as an owner-reviewed attestation, not as an automated legal determination. Review whether its freshness and reference requirements are adequate.

### C. Extraction, parser isolation, and prompt injection

Verify that:

1. Only supported HTML, plain-text, and PDF types are accepted.
2. Input bytes, pages, per-page text, total extracted characters, parse duration, and worker memory/CPU are bounded.
3. Malformed, encrypted, oversized, or unsupported documents fail safely without unbounded resource use.
4. HTML extraction excludes active/non-visible content as intended and cannot trigger network access.
5. PDF/HTML workers receive minimal environments and no provider credentials or unnecessary secrets.
6. Worker isolation claims are precise: assess the limits of POSIX resource limits and the absence of a separate network namespace or stronger OS sandbox.
7. Source text is always treated as untrusted data, never as instructions that can override system/developer prompts or validation rules.
8. Raw response bodies, arbitrary page text, secrets, and untrusted instructions are not persisted in retry ledgers or durable diagnostics.

### D. Evidence semantics and candidate integrity

Verify that:

1. Evidence records are bound to exact approved source URLs and reserved variant IDs.
2. Source IDs, URL canonicalization, timestamps, content types, locators, quote spans, and excerpt sizes are validated.
3. Every required non-null technical/price/registration/identity claim has the required source and bounded quote/locator binding.
4. Mismatched URLs, variants, fabricated identifiers, duplicate IDs, missing evidence, unsupported claims, excessive counts, and malformed JSON fail closed.
5. A quote's presence is not incorrectly treated as semantic relevance or factual support.
6. HTTP 2xx and `retrieved_unverified` are never treated as proof that a claim is correct.
7. Normalization cannot silently convert an unsupported or fabricated claim into an accepted claim.

### E. Pipeline ordering, auditor independence, and zero-bypass behavior

Trace the production call graph and verify that:

1. The readiness gate is checked before any research work.
2. Owner manifest/variant coverage and evidence preflight happen before proposal checkout, state overlay, or durable mutation.
3. Candidate parsing and deterministic schema/identity/evidence validation complete before either paid auditor is invoked.
4. Rejected candidates produce zero auditor calls.
5. Both independent auditors receive the same bounded, validated candidate/evidence bundle.
6. The two independent vendor PASS requirement cannot be bypassed by malformed verdicts, retries, fallback paths, exceptions, or partial responses.
7. Failed candidates cannot reach auditors or become promoted/accepted through retry, restart, proposal recovery, or cross-process state reconciliation.
8. A failure at any preflight/retrieval/extraction/validation stage leaves queue, proposal, ledger, and acknowledged state unchanged where the contract requires no mutation.
9. The hard-disabled readiness flag and research pause cannot be changed by candidate data, provider output, environment fallback, or an ordinary task/PR path.

### F. Operational and supply-chain considerations

Assess dependency and parser risk, secret exposure, logging, exception handling, test realism, CI coverage, workflow permissions, and whether any development or diagnostic path can invoke retrieval outside the readiness gate. Identify assumptions that require deployment-level controls rather than repository code.

## 5. Existing proof and its limits

The repository contains synthetic/local tests for policy decisions, retrieval controls, extraction limits, evidence binding, candidate validation, orchestration order, and recovery. The documented suite also includes subprocess proofs for retrieval preflight failure, robots denial, target-server failure, retry recovery, abrupt interruption, and cross-process state reconciliation.

These tests are useful evidence but have explicit limits:

- Mocked and synthetic tests do not prove OEM source permission or live-site behavior.
- A pinned-transport unit test must be inspected to ensure it exercises the real connection seam rather than only a mocked resolver.
- Quote/locator validation proves traceability to supplied source text, not semantic relevance or factual truth.
- A passing CI run does not replace independent security analysis.
- The worker resource limits do not, by themselves, prove complete OS sandboxing or network isolation.

The reviewer should independently reproduce important claims, identify gaps, and state which conclusions are code-reviewed, test-reproduced, or assumed.

## 6. Required reviewer deliverable

Please provide a written report containing:

1. **Identity and independence disclosure** from section 1.
2. **Exact reviewed repository and commit SHA**.
3. **Scope and exclusions**, including any files, call paths, tests, or deployment controls not reviewed.
4. **Verdict:** `PASS`, `PASS WITH CONDITIONS`, or `FAIL`.
5. **Findings**, each with:
   - Unique ID and severity (Critical/High/Medium/Low/Informational).
   - Affected file and line range at the reviewed SHA.
   - Preconditions and attack scenario.
   - Concrete impact.
   - Reproduction steps or a reason reproduction is not possible.
   - Recommended remediation.
6. **Acceptance-criteria matrix** mapping each requirement in issue #37 to Pass / Fail / Not Tested / Not Applicable, with evidence.
7. **Tests and tools used**, including commands, versions, and results.
8. **Residual risks and deployment assumptions**.
9. **Explicit statement** whether any live network request, OEM access, provider call, or production-state mutation was performed.
10. **Re-review requirements**, including the exact commit SHA required after remediation.

A PASS must not be issued while a Critical or High finding remains unresolved. A conditional verdict must list objective closure conditions. Findings must be tied to the exact SHA and must distinguish verified vulnerabilities from defense-in-depth recommendations.

## 7. Stop conditions and acceptance

The reviewer must stop and notify the owner if testing would require live OEM requests, external scanning, paid providers, manifest changes, retrieval activation, or mutation of the Hive queue/state.

Issue #37 remains open until the independent report is received, findings are resolved, exact-head CI/security checks pass, owner source review is completed for any proposed source entries, and the owner separately authorizes any future activation.

**This brief is a review handoff only. It is not an audit result, security certification, source-access permission, or activation approval.**
