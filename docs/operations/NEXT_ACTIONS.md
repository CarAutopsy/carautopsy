# Next Actions

**Last reconciled:** 2026-11-12  
**Authoritative sequence:** [ROADMAP.md](ROADMAP.md)

## Immediate

1. Arrange an independent human/external auditor for issue #47. The audit must use the exact merged PR #43 head recorded in that issue and include independence disclosure, verdict, findings, and scope limitations.
2. Arrange an independent external security review for issue #37, covering the integrated source-policy, DNS-pinned transport, extraction, evidence, candidate gate, orchestration ordering, and retry/restart/state-reconciliation behavior.
3. Review and approve any proposed exact OEM source hostname, URL, and automated-access terms before adding it to the owner-controlled manifest.
4. Resolve all independent audit findings and run the full validation suite on the exact final commit.
5. Keep retrieval paused until every acceptance gate is complete and the owner explicitly authorizes activation.

## Implemented on main

- Source retrieval and policy helpers enforce exact owner-controlled host/URL scope, fail-closed robots/terms checks, DNS-pinned HTTPS, bounded responses, and safe diagnostics.
- HTML, plain-text, and PDF extraction is bounded; raw source bytes are not persisted in candidate evidence or durable diagnostics.
- Claim-level evidence bindings require exact quoted spans and structured locators. This proves traceability to supplied source text, not semantic relevance or factual truth.
- The runtime path preflights policy/evidence across the main, Hive state, and open proposal queue snapshots before proposal checkout/state overlay.
- Deterministic candidate/identity/evidence validation runs before either independent auditor. Both auditors receive the same bounded prompt/evidence bundle and must return an exact standalone PASS token.
- Subprocess tests cover policy/retrieval failure without durable mutation, retry recovery, abrupt process interruption, and cross-process state reconciliation.
- Full TCO mode leaves the Hive research queue untouched; provider smoke-test routing remains separate.

## Required verification

- Full Python unit suite and catalog validation.
- Recursive compilation of scripts and tests.
- Repository Audit and relevant GitHub Actions checks on the exact final SHA.
- Independent human/external audit for #47 and independent external security review for #37.
- Owner review of every source manifest entry and automated-access terms.

## Do not do yet

- Do not populate `data-connectors/approved-source-hosts.json`.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove `HIVE_RESEARCH_PAUSED`.
- Do not perform live OEM retrieval or paid provider calls.
- Do not dispatch or automatically retry the queued vehicle research entries.
- Do not treat previous failed candidate records as verified data.
