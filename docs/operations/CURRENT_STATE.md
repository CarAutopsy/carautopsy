# Current Project State

**Last updated:** 2026-11-12  
**Repository:** CarAutopsy/carautopsy  
**Default branch:** `main`  
**Current mode:** GitHub + GitHub Actions development

## Confirmed completed

- PR #43 merged: prompt/schema contract documentation and schema tests. The owner explicitly waived the independent-audit prerequisite for that merge; the waiver did not satisfy issue #47.
- PR #49 merged: schema-aligned prompt builders and deterministic candidate/evidence validation helpers.
- PR #50 merged: DNS-pinned HTTPS retrieval primitive.
- PR #52 merged: owner-controlled exact-host/URL policy, robots handling, bounded HTML/plain-text/PDF extraction, and claim-level quote/locator evidence bindings.
- PR #53's zero-bypass integration contract is on `main` through PR #56.
- PR #57 merged: runtime research orchestration wires retrieval preflight, evidence collection, researcher prompt, deterministic candidate validation, and two independent auditors. The path is integrated but deliberately unreachable while the research readiness gate is closed.
- PRs #58–#60 merged: subprocess proofs for retrieval preflight, robots denial, and target-server failure without durable mutation.
- PRs #61–#63 merged: retry recovery, abrupt-interruption recovery, and cross-process state reconciliation proofs.
- PRs #64–#68 closed/merged or superseded as recorded in the PR history; the final reconciliation follow-up exposes the public read-only `fetched_state_tip()` accessor while retaining the acknowledgment-enforcing `proposal_state_base()` API.
- PR #69 merged: Qodo review configuration for PR events, pushes, draft feedback, and bot-authored commit push reviews.
- Issue #44 (prompt builders and deterministic candidate gates) and issue #45 (no-retrieval safety stop) are closed.

## Active Hive status

- Open acceptance issues: #37 (source provenance/retrieval security and external security review) and #47 (independent third-party audit of the prompt-overhaul documentation/schema tests).
- Runtime orchestration is integrated, but not production-enabled.
- `data-connectors/approved-source-hosts.json` intentionally has empty `approved_hosts` and `source_policies` arrays.
- `VERIFIED_RETRIEVAL_AVAILABLE = False`; `HIVE_RESEARCH_PAUSED` remains active.
- Full TCO mode remains separate from Hive research; provider smoke-test routing remains separate.
- No live OEM retrieval, paid research calls, or vehicle research dispatch is authorized.
- The vehicle queue and failed-candidate ledger remain quarantined while research is paused. Do not automatically retry or promote failed records.

## Remaining acceptance work

1. Obtain the independent human/external audit required by issue #47 against its specified merged commit and record auditor identity, independence, disclosure, verdict, findings, and exact SHA.
2. Obtain the independent external security review required by issue #37 against the integrated retrieval/orchestration implementation. Automated AI reviews do not substitute for either independent human audit.
3. Have the owner review each proposed exact OEM/official hostname, exact URL, source relevance, and automated-access terms before any manifest entry is added.
4. Resolve all audit findings and run exact-head CI/security validation.
5. Only after all acceptance criteria are met, obtain explicit owner authorization before considering retrieval activation.

See [ROADMAP.md](ROADMAP.md), [NEXT_ACTIONS.md](NEXT_ACTIONS.md), and [HIVE_PIPELINE_INTEGRATION.md](HIVE_PIPELINE_INTEGRATION.md).

## Operational constraints

- Do not add hosts or exact URLs to the approved manifest without owner review.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove the research pause as part of intermediate implementation PRs.
- Do not use paid provider calls or live source requests in unit/CI tests.
- Do not treat schema validity, quote presence, or HTTP 2xx as proof that a vehicle claim is true.
- Preserve two independent vendor PASS verdicts and required human review.
