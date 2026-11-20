# Engineering-agent pipeline — Phase 2 design proposal (not authorized)

**Status:** Design proposal only. No runtime, workflow, policy, manifest or activation change is made by this document.
**Tracking:** issue #114; evidence basis `docs/operations/CIVLAB_AUTOMATION_REUSE_ASSESSMENT.md`.
**Baseline:** CarAutopsy `main` at `cf53dbd142729c80c2ce45bfa38d294482a99fe4`.
**Date:** 2026-11-20.

This document proposes the design called for by issue #114 Phase 2. It does **not** authorize implementation, provider calls, live source retrieval, recurring execution, a second task scheduler, or any change to Hive's research gates. Every item in Section 13 remains an owner decision.

## 1. Goals and non-goals

### Goals

1. A separate, manually dispatched engineering-code capability that can propose small repository changes as **draft PRs only**.
2. One canonical controller, deterministic verification, two independent audits, and an explicitly gated publication step.
3. Reuse CarAutopsy's existing state, outcome, retry and read-only reporting primitives instead of duplicating them.
4. Make every spend, retry, failure and publication limit an executable, tested control — CivLab's own policy records monetary enforcement as `false`, so documentation alone is never accepted as enforcement.

### Non-goals / hard boundaries

- No replacement of Hive research, provenance retrieval, source policy, two-vendor candidate quorum, `hive/state` reconciliation, or the read-only issue-roadmap pipeline.
- No inheriting Hive's source allow-list or `VERIFIED_RETRIEVAL_AVAILABLE` as authority to execute code.
- No second state ledger, provider retry system, roadmap controller or recurring scheduler.
- No direct push to `main`; no non-draft PR; no autonomous merge.
- No live provider call, paid spend, or live source request without a separate explicit owner decision after these gates are implemented and tested.

## 2. Traceability: what is reused, adapted, preserved or rejected

| Capability | CivLab source | CarAutopsy target | Decision |
|---|---|---|---|
| Task eligibility / contract | #26, #32, #57, #204–#209 | New engineering task contract; `issue_roadmap_controller.py` remains the issue-intake authority | **Adapt** |
| Single canonical controller | #36, #90, #123–#127 | One new `engineering_agent.py` CLI; no second `.yml` loop | **Adapt** |
| Bounded pilot / allow-listed paths | #57, #72, #73 | New path allow-list and immutable snapshot helper | **Adapt** (do not reproduce #72's bytecode-cache artifact mistake) |
| Sandbox isolation | #26, pipeline_security.py | New isolated runner with no secrets, bounded CPU/memory/time | **Adapt**; mocked tests are not proof of real isolation |
| Verification failure evidence | #177–#179 | New verification-evidence artifact and bounded correction feedback | **Adapt** |
| Provider faults vs task defects | #87, #136 | Reuse `provider_retry.py` semantics; separate engineering outcome namespace | **Preserve distinction** |
| Draft-PR publisher + uncertain-write reconciliation | #32, #92, #126, #127 | New publisher step; consult `hive_pr.py` for existing PR-selection discipline | **Adapt**, separate from research PRs |
| Owner digest / roadmap reporting | #180–#185 | `hive_owner_digest.py`, `hive_owner_digest_snapshot.py`, `issue_roadmap_*` | **Preserve**; read-only reporting only |
| Persistent state / ledger digest | pilot_state.py, #181–#183 | `hive_state.py` primitives with an explicit engineering namespace — one ledger implementation | **Preserve / reuse**, never a second ledger |
| Typed failure taxonomy | #87, #177 | `hive_outcomes.py` for Hive; engineering-only classes in a separate namespace | **Preserve Hive**, add no engineering class to Hive |
| SQLite ledger | pilot_state.py | JSON `hive/state` branch | **Reject** |
| Provider registry | #88 | Static `PROVIDERS` in `autonomous_pipeline.py`; deferred per assessment §5.6 | **Defer** |
| Monetary budget claim | #90, #124 | New reservation/settlement contract with executable tests | **Design requirement**, not yet implemented |

## 3. Proposed workflow (one controller, one manual entry point)

Proposed new file: `.github/workflows/engineering-agent.yml`.

- Trigger: `workflow_dispatch` only at first. **No `schedule`.** No recurring or paid execution.
- Top-level permissions: `contents: read`. No job receives `issues: write`, `pull-requests: write`, or `contents: write` except the final publisher, and that job receives them only after audit evidence is verified.
- Same least-privilege job-graph discipline as `tests/test_autonomous_pipeline_workflow.py`: separate concurrency group, read-only generation/verification/audit jobs, a single narrowly scoped publication job.
- No provider secrets in the generation/verification sandbox; secrets are injected only into the separately gated provider step, and only after an owner-approved spend decision exists.

Sequence (each step emits a deterministic evidence artifact before the next can run):

1. **Reserve task** — select one eligible engineering task; write a reservation record through existing state primitives.
2. **Freeze snapshot** — capture exact base SHA, allow-listed paths, and a content digest of input files. Issue text and AI output are untrusted data, never instructions.
3. **Generate** — isolated candidate change, bounded patch size and path scope.
4. **Verify** — deterministic tests, compilation, repository audit, and policy checks; no network and no secrets.
5. **Audit** — two independent vendor verdicts over the immutable verification bundle; advisory AI cross-review is recorded separately and is not a quorum substitute.
6. **Publish** — create a **draft** PR only; on uncertain remote response, reconcile against GitHub rather than retrying blindly.
7. **Record** — append outcome, evidence digests and owner-decision pending markers to the existing ledger namespace.

## 4. Trusted task contract

Proposed fields, validated deterministically before any generation:

- `task_id` — stable namespaced key (e.g. `eng-001`), never derived from issue body text.
- `repository`, `base_sha` — exact immutable target.
- `allowed_paths` — explicit allow-list; anything outside fails closed.
- `goal`, `acceptance_criteria` — owner-approved, structured, non-empty; untrusted issue text may be *attached as evidence* but cannot set these fields.
- `max_patch_bytes`, `max_files_touched`, `timeout_seconds`, `max_provider_calls`, `max_spend_units` — hard bounds.
- `dependencies`, `requires_owner_approval`, `source_ref` — issue/PR/CI references with exact SHA where applicable.

A task is ineligible if any field is malformed, if dependencies are not satisfied, if the base SHA is stale, or if the acceptance criteria are not expressed as testable checks.

## 5. Immutable snapshot and allowed paths

- The controller captures `base_sha` and a SHA-256 manifest of every in-scope file before generation.
- The sandbox receives only allow-listed files plus the task contract. Verification re-computes the manifest; any mismatch fails closed.
- Generated patches are validated for: path allow-list, no symlink/escape, bounded size, no binary or bytecode artifacts, no workflow/policy files unless the task explicitly names them and owner approval is recorded.
- The repository's protected gates (`VERIFIED_RETRIEVAL_AVAILABLE`, `HIVE_RESEARCH_PAUSED`, approved-source manifest) are **never** writable by an engineering task.

## 6. Verification gate and evidence artifacts

Verification is deterministic and offline:

- recursive compilation, full Python unit suite, catalog validation where relevant, `scripts/repo_audit.py`;
- workflow contract tests (pattern established by `tests/test_autonomous_pipeline_workflow.py`);
- patch/snapshot integrity and path-bound checks;
- explicit assertions that no live source request or provider call occurred.

Evidence artifact (JSON, stable/diffable) contains: task ID, base SHA, source-manifest digest, patch digest, commands run, exit codes, test counts, workflow run URL, and exact SHA. A verification failure carries its evidence forward as bounded correction feedback (#177–#179), not a generic retry prompt.

## 7. Independent audit gate

- Two independent vendor verdicts are required over the same immutable bundle. They are distinct from Hive's two-vendor *research candidate* quorum and must not reuse a research PASS.
- A verdict is valid only when bound to the exact evidence digest and base SHA. Missing, stale or ambiguous verdicts fail closed.
- The five-service AI cross-review remains advisory and separately recorded; it never substitutes for the two-vendor quorum.
- Provider transport/format faults are recorded separately from verification failures and do not consume the code-revision allowance (#87, #136).

## 8. Draft-PR publication gate and uncertainty reconciliation

- Publication requires: verification PASS, two valid audit PASS verdicts, all spend/retry counters within limits, and an explicit owner-approval marker.
- The publisher creates a **draft** PR only. It never merges, never requests review autonomously, and never pushes to `main`.
- If a branch update or PR creation returns an uncertain result, the attempt stays unresolved and is reconciled against GitHub before any further action — no blind retry (#127).
- Existing-draft detection and rerun refusal must be regression-tested (#126).

## 9. Failure taxonomy, correction and reconciliation

Engineering-only classes live in a separate namespace; none is added to `hive_outcomes.py`:

- `contract_invalid` — task contract or acceptance shape invalid; stop before generation.
- `verification_failure` — deterministic verification failed; correction must cite the failing evidence.
- `sandbox_failure` — isolation/resource violation; fail closed, no retry against the same sandbox contract.
- `provider_error` — transport/format fault; bounded retry that does not consume revision allowance.
- `budget_exhausted` — reservation ceiling reached; stop, no further provider call.
- `publication_uncertain` — reconcile before retry.

Correction is bounded by `max_revisions`, and each revision must reference a specific verification/audit finding. Reconciliation uses the existing `hive_state.py` branch-digest and proposal-ancestry model with an explicit engineering namespace — one ledger implementation, no SQLite, no second controller. Owner digest output is a read-only projection of that ledger.

## 10. Hard spend limits (must be enforced in code)

Design contract, not yet implemented:

- `max_spend_units` and `max_provider_calls` are task-contract fields checked **before** each provider call.
- A reservation is persisted before a call and settled afterward; an unresolved reservation blocks the next attempt until reconciled.
- Exhaustion produces `budget_exhausted` and a hard stop; no "best effort" continuation.
- Required proof: tests that drive the limiter to its boundary and assert zero provider calls beyond it, including crash/restart and uncertain-response paths. A policy file saying enforcement is enabled is not acceptable evidence.

## 11. Test strategy

- No secret, no live provider, no live source request in any unit/CI test.
- Static workflow contract tests for job graph, permissions, artifact names and fail-fast behavior.
- Pure contract/validation tests for malformed and conflicting task metadata, deterministic ordering, idempotency and input non-mutation — the same standard applied in PR #118.
- Deterministic verification/evidence tests, two-vendor quorum tests, publication gate tests, rerun/existing-draft tests, uncertain-write reconciliation tests, and budget boundary tests.
- Sandbox isolation claims must distinguish mocked-boundary tests from demonstrated runtime isolation; do not claim end-to-end proof from a mock.

## 12. Implementation sequence (one component per PR, none merged here)

1. Task-contract schema and pure validators + tests (design → code only after owner approval).
2. Snapshot/path allow-list helper + tests.
3. Verification runner and evidence artifact + tests.
4. Two-vendor audit gate + tests.
5. Owner-gated draft publisher with reconciliation + tests.
6. Namespaced ledger outcomes and owner digest projection + tests.
7. Reservation/settlement spend limiter + boundary tests.
8. Workflow definition and static workflow-contract tests.
9. Only then, an owner-authorized no-secret end-to-end dry run.

Each PR carries regression tests and independent audit evidence. No PR in this sequence may enable recurring execution or spend.

## 13. Explicit owner decisions still required

1. Approve (or reject) a separate engineering-agent capability at all.
2. Choose the task source and who may set `allowed_paths` and acceptance criteria.
3. Approve the ledger namespace choice (reuse `hive/state` with namespace vs. a separately approved branch) without creating a second ledger implementation.
4. Define the two-vendor audit roster and confirm it is independent of the research-candidate quorum.
5. Define spend units, ceilings and who authorizes any provider call; decide whether any smoke test is ever permitted.
6. Define owner-approval mechanics for publication (a YAML environment name alone is not proof of human approval).
7. Approve each implementation PR after exact-head CI and independent audit; no autonomous merge.

## 14. Safety invariants (unchanged)

1. Candidate/AI output never controls hosts, URLs, variant identity, policy approval or allowed paths.
2. Empty or invalid policy fails closed; protected Hive gates are never writable by engineering tasks.
3. The owner records the final human verdict; AI output is advisory and traceable.
4. No live retrieval, paid provider call, queue dispatch, non-draft PR or activation without explicit owner authorization.
5. One ledger, one controller, one roadmap pipeline; no duplicated automation or retry machinery.
6. A green check, a draft PR or a successful dry run is evidence of that step only — never of factual vehicle data, source permission or owner approval.
