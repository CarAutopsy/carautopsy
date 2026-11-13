# Next Actions

**Last reconciled:** 2026-11-13  
**Authoritative sequence:** [ROADMAP.md](ROADMAP.md)

## Immediate

1. Complete the owner human audit for issue #47 against the exact merged PR #43 target SHA. Record PASS / PASS WITH CONDITIONS / FAIL, findings, severity, and limitations.
2. Complete the owner security review for issue #37 against the integrated retrieval/orchestration implementation. Obtain and record cross-review from all five AI services already in use, including findings, disagreements, unresolved risks, and residual limitations.
3. Review and approve each proposed exact OEM source hostname, URL, source relevance, and automated-access terms before adding any entry to the owner-controlled manifest.
4. Resolve all findings and run the full validation suite, catalog validation, module compilation, and Repository Audit on the exact final SHA.
5. Keep retrieval paused until review criteria are complete and the owner explicitly authorizes activation.

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

## Required verification

- Full Python unit suite and catalog validation.
- Recursive compilation of scripts and tests.
- Repository Audit and relevant GitHub Actions checks on the exact final SHA.
- Owner human audit for #47 and owner security review for #37.
- Five-service AI cross-review for #37, with findings/disagreements/residual risks recorded.
- Owner review of every source manifest entry and automated-access terms.

## Do not do yet

- Do not populate `data-connectors/approved-source-hosts.json`.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove `HIVE_RESEARCH_PAUSED`.
- Do not perform live OEM retrieval or paid provider calls.
- Do not dispatch or automatically retry the queued vehicle research entries.
- Do not treat previous failed candidate records as verified data.
- Do not confuse the five-service security cross-review with the two independent vendor PASS verdicts required for each candidate.
