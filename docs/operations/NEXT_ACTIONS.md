# Next Actions

**Last reconciled:** 2026-11-22  
**Authoritative sequence:** [ROADMAP.md](ROADMAP.md)

## Immediate

1. Decide the disposition of draft PR #144, whose bulk-ingestion scope overlaps
   the already-merged PR #145 (close as superseded, or keep as a narrower
   follow-up). [OWNER_DECISION]
2. Reconcile stale project state and session handover with merged `main` at
   `245f8fd`. **DONE 2026-11-22** — see
   `.carautopsy/sessions/CARAUTOPSY-SESSION-OPENCODE-20261122-0502-001.md`. [TRACE_EXECUTION]
3. Complete the owner human audit for issue #47 against the exact merged PR #43 target SHA. Record PASS / PASS WITH CONDITIONS / FAIL, findings, severity, and limitations.
4. Complete the owner security review for issue #37 against the integrated retrieval/orchestration implementation. Obtain and record cross-review from all five AI services already in use, including findings, disagreements, unresolved risks, and residual limitations.
5. Review and approve each proposed exact OEM source hostname, URL, source relevance, and automated-access terms before adding any entry to the owner-controlled manifest.
6. Select the next engineering workstream: enrich the sparse EEA-sourced
   variants (the P1 refresh backlog) or continue with owner acceptance reviews.
   [OWNER_DECISION]
7. Resolve all findings and run the full validation suite, catalog validation, module compilation, and Repository Audit on the exact final SHA.
8. Keep retrieval paused until review criteria are complete and the owner explicitly authorizes activation.

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
- Offline catalog quality and bulk-ingestion tooling landed on main (#140, #141, #145): canonical normalization, duplicate/conflict detection, completeness metrics, refresh planning, evidence harvesting and branch-scoped staging. Nothing writes `catalog/variants/` or opens a socket. [STATIC_READ]
- 120 catalog records are on main from owner-approved batches 001/002 plus EEA evidence; 114 of 154 2018 AT sample rows are identity/price resolved and already present, so repeated ingestion is idempotent with zero writes. [STATIC_READ]
 
## Required verification

- Full Python unit suite and catalog validation.
- Catalog quality report on the exact final SHA (`python scripts/catalog_quality.py --report <temp> --now <fixed>`), recording variant count, structural errors, blocking findings and completeness. The 2026-11-22 reading at HEAD `245f8fd` is 120 / 0 / 0 / 0.2633. [TRACE_EXECUTION]
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
- Do not treat the 120 catalog records, or their completeness score, as verified vehicle data; most EEA-sourced records still have P1 critical-field gaps. [OWNER_DECISION]
- Do not dispatch, promote or catalog-write staging output from `scripts/ingest_bulk_catalog.py` without a separate owner-approved batch PR. [OWNER_DECISION]
