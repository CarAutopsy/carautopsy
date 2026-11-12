# CarAutopsy engineering roadmap

**Last reconciled:** 2026-11-12  
**Default branch:** `main`  
**Scope:** Hive research safety, evidence integrity, orchestration, and vehicle-data readiness.

This is the operational roadmap for the Hive workstream. GitHub issues remain the source of truth for issue discussion and acceptance; this document provides the dependency order and current project-level status.

## Current operating state

- PR #43 (prompt/schema contract) is merged to `main` under an explicit owner waiver of the independent-audit prerequisite. The waiver did not complete the audit tracked by issue #47.
- PR #49 (prompt builders and deterministic candidate/evidence gate) is merged.
- PR #50 (DNS-pinned HTTPS transport) is merged.
- PR #52 (source policy, robots checks, bounded extraction, and claim-level evidence bindings) is merged to `main`.
- PR #53 (zero-bypass integration contract) is merged into `feat/hive-source-policy-extraction`, not directly into `main`. PR #56 brings the contract onto `main` as documentation.
- PR #57 is a draft runtime-integration PR. Its current head `96a624ebcc422626fdc6d2600bdd86a3cc4d77b9` wires the orchestration seam behind the hard research stop, preflights evidence before proposal/state changes, and has passing CI (268 tests, catalog validation, compilation, Repository Audit). Full TCO mode remains a catalog-only calculation and leaves the Hive queue untouched. It is not merged or activation-ready.
- `data-connectors/approved-source-hosts.json` remains empty.
- `VERIFIED_RETRIEVAL_AVAILABLE` remains `False`; `HIVE_RESEARCH_PAUSED` remains active.
- No live OEM retrieval, paid provider calls, or new vehicle research dispatch is authorized.

## Open work and dependencies

| Order | Workstream | GitHub issue | Status | Depends on |
|---:|---|---|---|---|
| 1 | Prompt/schema contract independent audit | [#47](https://github.com/CarAutopsy/carautopsy/issues/47) | Open; independent human/external audit outstanding | Merged PR #43 |
| 2 | Runtime prompt and deterministic candidate-gate integration | [#44](https://github.com/CarAutopsy/carautopsy/issues/44) | Draft implementation in PR #57; runtime acceptance and full failure-path proof remain | #49, #52, #53 contract |
| 3 | Retrieval, provenance, and zero-bypass integration | [#37](https://github.com/CarAutopsy/carautopsy/issues/37) | Draft integration in PR #57; end-to-end retry/restart/state-reconciliation proof and external security review remain | #49, #50, #52, #53 |
| 4 | Integrated security and operational review | Tracked under #37 and #47 | Not complete | Final integrated PR head |

Issue #45 (no-retrieval safety stop) is closed. Its zero-spend/no-state-mutation guarantees remain mandatory regression requirements.

## Milestones

### M0 — Roadmap and contract reconciliation

- [x] Confirm merged PRs and actual target branches.
- [ ] Merge the PR #53 integration contract onto `main` through documentation PR #56.
- [x] Establish this dependency-ordered roadmap and refresh operational handover documents.
- [ ] Review and merge PR #56.

### M1 — Confirm the deterministic gate boundary

- [x] Inspect the exported APIs in `scripts/hive_prompts.py`, `scripts/hive_candidate.py`, `scripts/hive_evidence.py`, and `scripts/hive_source_policy.py`.
- [x] Reconcile issue #44 with the helper implementation merged in #49; avoid duplicating helper work.
- [x] Define a callable orchestration seam that returns only a validated candidate/evidence pair.
- [x] Preserve side-effect-free imports and exact reserved task identity.
- [ ] Merge and audit the implementation in PR #57.

### M2 — Runtime integration (primary engineering milestone)

*Implementation is in draft PR #57; keep this milestone open until review and integration acceptance are complete.*

- [x] Wire retrieval → researcher prompt → bounded JSON parse → deterministic candidate validation → two independent auditors.
- [x] Build one auditor prompt from the validated candidate/evidence and send identical inputs to two distinct vendors.
- [x] Require an exact standalone `PASS` token.
- [x] Keep full TCO calculation isolated from research dispatch; the queue is untouched in full mode.
- [x] Preflight and validate evidence for the upcoming main/state/proposal queue snapshots before proposal checkout or state overlay.
- [ ] Prove all retry, restart, existing-proposal, and state-branch paths cannot bypass the same gate.
- [ ] Complete end-to-end failure-path tests and merge the reviewed implementation.
- [ ] Keep `VERIFIED_RETRIEVAL_AVAILABLE = False` and the research pause active throughout implementation.

### M3 — Zero-bypass and zero-spend proof

- [ ] Empty/malformed manifest and denied/unavailable robots: zero target fetches where policy requires preflight denial; zero provider calls; zero durable state changes.
- [ ] Extraction/transport failure: zero researcher and auditor calls; no candidate publication or proposal/state mutation.
- [ ] Malformed JSON, schema/identity/provenance/quote/locator mismatch: zero auditor calls.
- [ ] Accepted candidate: both auditors receive equivalent immutable candidate/evidence inputs.
- [ ] Retry/restart and existing-proposal paths cannot bypass the gate.
- [ ] Provider failures, provenance rejection, and operational pause remain distinct outcomes.
- [ ] Run full Python tests, catalog validation, recursive compilation, Repository Audit, and relevant workflow checks on the exact final SHA.

### M4 — Independent review and activation decision

- [ ] Complete issue #47 with an independent human/external auditor and exact-SHA report.
- [ ] Obtain an independent security review of the integrated retrieval and orchestration path.
- [ ] Resolve findings and record evidence against the exact final SHA.
- [ ] Obtain explicit owner authorization before any activation decision.
- [ ] Only after authorization may source URLs be considered for the owner-reviewed manifest; never populate it from candidate output.

## Vehicle-data backlog

- `tasks/queue.json` currently contains 23 reserved vehicle variants.
- `tasks/failed.json` contains previously rejected candidates and audit diagnostics.
- Do not dispatch or automatically retry these records while the research pause is active.
- After M3/M4 gates are satisfied and activation is explicitly authorized, process a small pilot batch. Preserve rejected candidates and their diagnostics; do not silently overwrite or promote them.
- A schema-valid candidate or an HTTP 2xx response is not verified vehicle data. Claim support, source authenticity, market/year identity, and two independent vendor PASS verdicts remain separate requirements.

## Safety invariants

1. Candidate/model output never controls source hosts, URLs, variant identity, or policy approval.
2. Empty or invalid owner policy fails closed.
3. HTTPS transport remains DNS-pinned, redirect-rejecting, bounded, and exact-host constrained.
4. Raw source bodies, secrets, and untrusted page instructions are not persisted in retry/state records.
5. No candidate reaches either paid auditor before deterministic validation succeeds.
6. Both independent vendor PASS verdicts and required human review remain mandatory.
7. No live retrieval, paid provider calls, or research activation without explicit owner authorization.

## Change control

Update this roadmap when an issue changes state, a PR merges, a dependency is discovered, or an acceptance criterion changes. Record exact commit SHAs for validation and review claims. Never mark a milestone complete based only on documentation, mocked tests, or an AI-generated audit.
