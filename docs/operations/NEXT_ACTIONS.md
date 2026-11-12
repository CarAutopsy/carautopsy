# Next Actions

**Last reconciled:** 2026-11-12  
**Authoritative sequence:** [ROADMAP.md](ROADMAP.md)

## Immediate

1. Review and merge documentation-only roadmap PR #56.
2. Review draft runtime-integration PR #57; CodeRabbit manual review was requested, but the free review allowance is currently rate-limited.
3. Complete end-to-end tests for proposal/state reconciliation, retries, restarts, and zero durable mutation on retrieval/policy failures.
4. Keep issue #37 open until integration/security acceptance is complete.
5. Keep issue #47 open until a genuinely independent human/external audit is recorded against the exact reviewed SHA.

## Current implementation in PR #57

- Existing retrieval, prompt, candidate, and audit helpers are wired into one research path.
- Candidate schema, reserved identity, provenance, and claim evidence validation run before either auditor.
- Both auditors receive the same prompt and must return exact standalone PASS tokens.
- Policy coverage and evidence retrieval are preflighted across main, Hive state, and open proposal queue snapshots before proposal checkout or state overlay.
- Full TCO mode skips Hive dispatch and leaves the research queue untouched.\n- The readiness flag remains false and the approved source manifest remains empty.

## Required verification

- Full Python unit suite.
- Catalog validation.
- Recursive compilation of scripts and tests.
- Repository Audit and relevant GitHub Actions checks on the exact final commit SHA.
- Independent external security review before any activation decision.

## Do not do yet

- Do not populate `data-connectors/approved-source-hosts.json`.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove `HIVE_RESEARCH_PAUSED`.
- Do not perform live OEM retrieval or paid provider calls.
- Do not dispatch or automatically retry the 23 vehicle queue entries.
- Do not treat previous failed candidate records as verified data.
