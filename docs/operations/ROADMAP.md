# CarAutopsy engineering roadmap

**Last reconciled:** 2026-11-20  
**Default branch:** `main` (verified snapshot head `978a96c0dca4480e00528811ed4df18b49a6cdd8`)  
**Operating model:** one-person, zero-budget project; owner-led human review with cross-review from five AI services.

Evidence basis for this reconciliation: current GitHub issue/PR state, owner comments on issues #37 and #47, and workflow runs pinned below. Derived documents never override issue state or exact-SHA CI evidence.

This is the operational roadmap for the Hive workstream. GitHub issues remain the source of truth for discussion and acceptance; this document provides dependency order and project-level status.

## Current operating state

- PR #43 (prompt/schema contract) is merged under an explicit owner waiver of the then-planned audit prerequisite. The separate owner audit tracked by #47 is now CLOSED with PASS (see M1).
- PR #49 (prompt builders and deterministic candidate/evidence gate) is merged.
- PR #50 (DNS-pinned HTTPS transport) is merged.
- PR #52 (source policy, robots checks, bounded extraction, and claim-level evidence bindings) is merged.
- PR #57 (runtime orchestration) is merged and wired behind the hard research stop; evidence preflight and deterministic validation precede research auditors and state mutation.
- PRs #58–#63 and #67–#68 provide synthetic no-mutation, retry, interruption and state-reconciliation proofs.
- PR #69 Qodo review configuration is merged.
- PR #71 security review handoff documentation is merged; its process now follows the owner-led, zero-budget review model recorded here.
- PR #72 retrieval audit fixes are merged; exact-head CI passed on the PR head and post-merge validation passed on main.
- Issue #47 (owner audit of the PR #43 prompt/schema contract) is **CLOSED** with an explicit owner verdict of **PASS** recorded 2026-11-13. The audited target was reviewed head `492390abec21ea268b22829f1017242d9b930121` (squash-merge commit `647ff76af47c9f436b24e1bf5ad018962c8c91d3`). Findings F-47-01 and F-47-02 were resolved (the latter via merged PR #73) and F-47-03 was closed as informational. The verdict did not authorize retrieval or activation.
- Issue #37 remains **OPEN**. The 2026-11-20 audit-findings comment records substantial provenance-safety implementation complete (T-01, T-02, F-37-CHATGPT-01, T-03, T-06, T-07 resolved by merged PRs #74, #78, #80, #81, #83, #84). T-04's diagnostic URL path redaction is **implemented and merged** in PR #85 (2026-11-15, head `bf9c2f87729777074d11cae725d21c8589b88e23`); only its post-merge integration verification remains. The five-service AI cross-review, owner human security verdict, source curation and activation decision remain outstanding.
- Issue #86 (guarded issue-to-roadmap intake) remains **OPEN**. Draft PR #118 carries step-1 synthetic regression tests at head `005028a5bc9fe9990578d2ea5655256866e3b3c4`; exact-head audit/validate CI passed and an independent audit was requested. It is not merged.
- The issue-roadmap controller, reconciliation, artifact, apply-plan and evidence-collection work is merged through PRs #87, #90, #93, #95, #96, #99, #100, #101, #102 and #103. PR #120 is a draft evidence checklist only, not an acceptance record.
- Other merged follow-ups include PR #91 (TCO fail-closed readiness gate), #92 (web build / stale TCO guard), #115 (CivLab reuse assessment), #116 (read-only owner digest), #117 (bounded DeepSeek PR auditor), #122 (evidence-bundle bounds regressions), #123 (structured-locator regressions), #125 (engineering-agent design proposal), #126 (TCO write-boundary review) and #128 (fixture-only pilot). #125, #126 and #128 merged at 15:36 UTC. Open at this snapshot: #124 (workflow contracts), #127 (bounded PR fetch), #130 (TCO publication guard), #131 (pilot expansion), #132 (engineering foundation), plus drafts #118 and #120.
- Exact-head CI on snapshot main `978a96c`: Repository Audit [run #44765013835](https://github.com/CarAutopsy/carautopsy/actions/runs/44765013835) PASS; Validate Catalog [run #44765013903](https://github.com/CarAutopsy/carautopsy/actions/runs/44765013903) PASS. This is a pinned snapshot, not a claim about later commits. Earlier head `c3aad86` had Validate Catalog run 44747335215 PASS; `cf53dbd` had Validate Catalog run 44461265067 PASS, DeepSeek PR Auditor Tests run 44461264961 PASS, and paused-heartbeat Pipeline/Owner-Digest runs PASS (not data completion).

### Status vocabulary (implemented / tested / accepted / activated)

- **Implemented:** code merged to `main` (for example retrieval hardening PRs #74–#89, roadmap controller PRs #87–#103, T-04 PR #85, regression PRs #122–#123).
- **Tested:** exact-head CI green for that SHA (snapshot `978a96c`: Repository Audit run 44765013835 and Validate Catalog run 44765013903 both PASS).
- **Accepted:** an owner human verdict is recorded at an exact SHA. Only #47 is accepted (PASS). Issue #37 is **not accepted**.
- **Activated:** live retrieval/paid provider/research dispatch authorized. **None** — the manifest is empty, readiness is false and the pause is active. An implemented or tested change is never an acceptance or activation claim.
- `data-connectors/approved-source-hosts.json` remains empty (`approved_hosts` and `source_policies` are empty arrays).
- `VERIFIED_RETRIEVAL_AVAILABLE` remains `False` (`scripts/autonomous_pipeline.py:168`); `HIVE_RESEARCH_PAUSED` remains active.
- No live OEM retrieval, paid provider calls, or new vehicle research dispatch is authorized. A green heartbeat or a successful crawler-only run is workflow evidence only, never proof of data completion.

## Open work and dependencies

| Order | Workstream | GitHub issue | Status | Depends on |
|---:|---|---|---|---|
| 1 | Retrieval/provenance security and zero-bypass acceptance | [#37](https://github.com/CarAutopsy/carautopsy/issues/37) | Open; owner human security verdict, five-service AI cross-review, post-merge verification of T-04/PR #85 and no-bypass evidence outstanding | #49, #50, #52, #57–#90 |
| 2 | Guarded issue-to-roadmap intake | [#86](https://github.com/CarAutopsy/carautopsy/issues/86) | Open; draft PR #118 has step-1 regressions at `005028a`, exact-head CI PASS, independent audit requested, not merged | Merged controller PRs #87–#103 |
| 3 | Owner review of exact source approvals | [#37](https://github.com/CarAutopsy/carautopsy/issues/37) | Pending any proposed source; exact host/URL and automated-access terms must be reviewed before manifest change | #37 |
| 4 | Offline reconciliation and regression sprint | [#119](https://github.com/CarAutopsy/carautopsy/issues/119) | Open; work-package checkpoints posted there; no activation authority | #37, #86 |

Closed and recorded: #44 (prompt builders and deterministic candidate gates), #45 (no-retrieval safety stop) and #47 (owner audit PASS, see M1). Their guarantees remain mandatory regression requirements.

## M1 — Owner audit of prompt/schema contract (#47) — COMPLETE

Owner verdict **PASS** recorded 2026-11-13 in [issue #47](https://github.com/CarAutopsy/carautopsy/issues/47); issue is closed.

- [x] Pinned merged PR #43 target SHA: reviewed head `492390abec21ea268b22829f1017242d9b930121`, squash-merge commit `647ff76af47c9f436b24e1bf5ad018962c8c91d3`.
- [x] Owner recorded PASS / findings / severity / rationale; F-47-01 resolved on the audited head, F-47-02 resolved via merged PR #73, F-47-03 informational.
- [x] Review evidence recorded for CodeRabbit, Qodo, ChatGPT and Copilot; Perplexity had no recorded result and the owner explicitly waived it as a blocker under the zero-budget owner/AI review model. AI output is advisory, not independent human certification.
- [x] Recorded that no live provider calls, source retrieval or factual vehicle-data verification occurred.
- [x] Recorded scope limitations and PR #43 disposition (merged under an earlier owner waiver; this PASS completes only the narrow audit).
- [x] Recorded that this verdict does **not** authorize live retrieval, source-manifest changes or readiness activation.

## M2 — Retrieval, provenance and security acceptance (#37) — OPEN

Current evidence (2026-11-20 issue #37 audit-findings comment): T-01, T-02, F-37-CHATGPT-01, T-03, T-06 and T-07 are resolved via merged PRs. T-04 (diagnostic URL path redaction) is **merged** in PR #85 at head `bf9c2f8`; its post-merge integration needs verification on the exact current SHA. T-05 (platform CA trust residual) is an accepted residual. The integrated owner review, five-service cross-review and source/activation gates remain open. Do not mark acceptance complete without exact-SHA evidence.

- [ ] **Step 1 (before any review):** pin the exact integrated source SHA and identify files/call paths under review. Never begin the review against a moving head.
- [ ] **Step 2:** owner performs and records a human security review against that pinned SHA, covering SSRF/DNS pinning, TLS, URL parsing, robots/terms policy, extraction/parser safety, prompt injection, evidence semantics, candidate validation, auditor ordering, and retry/restart/state invariants.
- [ ] **Step 3:** cross-review with all five AI services already used by the project; record each service's exact SHA status, scope, findings, disagreements, unavailable/rate-limited reviews, unresolved risks and residual limitations.
- [ ] **Step 4:** run full Python tests, catalog validation, compilation, Repository Audit and exact-head workflows; record run URLs and SHA.
- [ ] **Step 5:** resolve findings, then re-pin the integrated SHA and repeat the affected review/check steps before recording a verdict. A review of an older head never satisfies acceptance for a newer one.
- [ ] Keep technical acceptance gates: fail-closed source policy; DNS-pinned HTTPS; bounded extraction; traceable claim evidence; deterministic candidate gate before research auditors; two independent vendor PASS verdicts; no retry/restart bypass.
- [ ] Owner reviews each proposed exact host, source URL, relevance and automated-access terms before any manifest update.

## M3 — No-bypass and no-spend regression proof — OPEN

Synthetic subprocess proofs are merged through PRs #58–#63, #67–#68 and #88–#89, and the offline no-bypass gaps are being extended under issue #119. Local full-suite results are host-dependent; record the exact Linux CI run URL and SHA before claiming completion.

- [ ] Empty/malformed manifest and denied/unavailable robots: deny before target fetch as required; zero provider calls; zero durable state changes.
- [ ] Extraction/transport failure: zero researcher/auditor calls; no candidate publication or proposal/state mutation.
- [ ] Malformed JSON, schema/identity/provenance/quote/locator mismatch: zero auditor calls.
- [ ] Accepted candidate: both research auditors receive equivalent immutable candidate/evidence inputs.
- [ ] Retry/restart and existing-proposal paths cannot bypass the gate.
- [ ] Provider failures, provenance rejection, and operational pause remain distinct outcomes.
- [ ] Run and record full validation on exact final SHA.

## M4 — Separate activation decision

- [ ] All #37/#47 review records and technical acceptance criteria are complete.
- [ ] All material findings are resolved or explicitly dispositioned with objective conditions.
- [ ] Source permissions and automated-access terms are reviewed for each exact proposed source.
- [ ] Owner makes a separate, explicit activation decision.
- [ ] Only after authorization may source URLs be considered for the owner-reviewed manifest; candidate output must never populate it.

## Vehicle-data backlog

- `tasks/queue.json` and `tasks/failed.json` contain reserved variants and previously rejected candidates/diagnostics.
- Do not dispatch or automatically retry these records while the research pause is active.
- After all review/technical gates and explicit owner authorization, process a small pilot batch. Preserve rejected candidates and diagnostics; do not silently overwrite or promote them.
- Schema validity or HTTP 2xx is not verified vehicle data. Claim support, source authenticity, market/year identity and the two independent vendor PASS verdicts remain separate requirements.

## Safety invariants

1. Candidate/model output never controls source hosts, URLs, variant identity or policy approval.
2. Empty or invalid owner policy fails closed.
3. HTTPS transport remains DNS-pinned, redirect-rejecting, bounded and exact-host constrained.
4. Raw source bodies, secrets and untrusted page instructions are not persisted in retry/state records.
5. No candidate reaches either research auditor before deterministic validation succeeds.
6. Two independent research-vendor PASS verdicts remain mandatory for candidate acceptance; the five-service AI cross-review is a separate security-review activity.
7. No live retrieval, paid provider calls or research activation without explicit owner authorization.
8. The owner records the final human verdict; AI cross-review remains advisory and fully traceable.

## Change control

Update this roadmap when an issue changes state, a PR merges, a dependency is discovered or an acceptance criterion changes. Record exact commit SHAs for validation and review claims. Never mark an audit complete based only on documentation, mocked tests or AI-generated output.
