# Next Actions

**Last reconciled:** 2026-11-20  
**Authoritative sequence:** [ROADMAP.md](ROADMAP.md)

## Immediate

1. **Pin first:** verify PR #85's merged T-04 diagnostic URL path redaction in current main and record the exact integrated commit SHA for #37. Do not begin a review against a moving head.
2. Complete the owner security review for issue #37 against **that pinned SHA**. Obtain and record cross-review from all five AI services already in use, including findings, disagreements, unresolved risks, and residual limitations. If any change lands during review, re-pin the SHA and repeat the affected checks before recording a verdict.
3. Review and approve each proposed exact OEM source hostname, URL, source relevance, and automated-access terms before adding any entry to the owner-controlled manifest.
4. Resolve all findings and run the full validation suite, catalog validation, module compilation, and Repository Audit on the exact final SHA.
5. Keep retrieval paused until review criteria are complete and the owner explicitly authorizes activation.

Recorded complete: issue #47 owner audit PASS (2026-11-13) at PR #43 reviewed head `492390abec21ea268b22829f1017242d9b930121`; do not reopen it as an immediate blocker. Track the offline sprint checkpoints in issue #119.

## Implemented on main

- Source retrieval and policy helpers enforce exact owner-controlled host/URL scope, fail-closed robots/terms checks, DNS-pinned HTTPS, bounded responses, and safe diagnostics.
- URL validation rejects malformed/nested encodings and placeholder identifiers; diagnostics redact credentials, query values and fragments.
- Retrieval uses a monotonic total deadline across policy callback, DNS, TCP, TLS and HTTP reads.
- HTML, plain-text, and PDF extraction is bounded; raw source bytes are not persisted in candidate evidence or durable diagnostics.
- Claim-level evidence bindings require exact quoted spans and structured locators. This proves traceability to supplied source text, not semantic relevance or factual truth.
- The runtime path preflights policy/evidence across main, Hive state, and open proposal queue snapshots before proposal checkout/state overlay.
- Deterministic candidate/identity/evidence validation runs before either independent research auditor. Both auditors receive the same bounded prompt/evidence bundle and must return an exact standalone PASS token.
- Subprocess tests cover policy/retrieval failure without durable mutation, retry recovery, abrupt process interruption, and cross-process state reconciliation.
- Full TCO mode leaves the Hive research queue untouched; provider smoke-test routing remains separate.
- The read-only issue-to-roadmap controller, reconciliation, proposal artifact, owner-approved apply planner and verified-evidence collector are merged (PRs #87, #90, #93, #95, #96, #99–#103). Draft PR #120 is an evidence checklist only.
- Owner audit #47 is closed with PASS; findings were resolved through PR #73. The TCO readiness gate, web build, owner digest, bounded DeepSeek PR auditor, Hive retrieval hardening, regression PRs #122–#123 and design/review/pilot PRs #125, #126 and #128 are merged on snapshot main `978a96c` (Repository Audit run 44765013835 and Validate Catalog run 44765013903 PASS at that exact head).
- Draft PR #118 adds step-1 synthetic classification/reconciliation regressions at head `005028a5bc9fe9990578d2ea5655256866e3b3c4` (59 targeted tests pass locally; exact-head audit/validate CI PASS); independent audit requested, not merged. Open at this snapshot: #124 (workflow contracts), #127 (bounded PR fetch), #130 (TCO publication guard), #131 (pilot expansion), #132 (engineering foundation), plus drafts #118 and #120. T-04/PR #85 is merged; only its post-merge integration verification remains.
- Implemented and tested are not accepted or activated: #47 is the only owner-accepted item; no activation exists (empty manifest, readiness false, research paused).

## Required verification

- Full Python unit suite and catalog validation.
- Recursive compilation of scripts and tests.
- Repository Audit and relevant GitHub Actions checks on the exact final SHA.
- Owner human audit for #47 — COMPLETE (PASS at the exact PR #43 reviewed head); owner security review for #37 — outstanding.
- Five-service AI cross-review for #37, with findings/disagreements/residual risks recorded.
- Owner review of every source manifest entry and automated-access terms.

## Do not do yet

- Do not populate `data-connectors/approved-source-hosts.json`.
- Do not treat a green heartbeat or a successful crawler-only/proposal-artifact run as verified data, source permission, or an owner decision.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove `HIVE_RESEARCH_PAUSED`.
- Do not perform live OEM retrieval or paid provider calls.
- Do not dispatch or automatically retry the queued vehicle research entries.
- Do not treat previous failed candidate records as verified data.
- Do not confuse the five-service security cross-review with the two independent vendor PASS verdicts required for each candidate.
