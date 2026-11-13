# CarAutopsy engineering roadmap

**Last reconciled:** 2026-11-13  
**Default branch:** `main`  
**Operating model:** one-person, zero-budget project; owner-led human review with cross-review from five AI services.

This is the operational roadmap for the Hive workstream. GitHub issues remain the source of truth for discussion and acceptance; this document provides dependency order and project-level status.

## Current operating state

- PR #43 (prompt/schema contract) is merged under an explicit owner waiver of the then-planned audit prerequisite. The owner human audit tracked by #47 remains a separate task.
- PR #49 (prompt builders and deterministic candidate/evidence gate) is merged.
- PR #50 (DNS-pinned HTTPS transport) is merged.
- PR #52 (source policy, robots checks, bounded extraction, and claim-level evidence bindings) is merged.
- PR #57 (runtime orchestration) is merged and wired behind the hard research stop; evidence preflight and deterministic validation precede research auditors and state mutation.
- PRs #58–#63 and #67–#68 provide synthetic no-mutation, retry, interruption and state-reconciliation proofs.
- PR #69 Qodo review configuration is merged.
- PR #71 security review handoff documentation is merged; its process now follows the owner-led, zero-budget review model recorded here.
- PR #72 retrieval audit fixes are merged; exact-head CI passed on the PR head and post-merge validation passed on main.
- `data-connectors/approved-source-hosts.json` remains empty.
- `VERIFIED_RETRIEVAL_AVAILABLE` remains `False`; `HIVE_RESEARCH_PAUSED` remains active.
- No live OEM retrieval, paid provider calls, or new vehicle research dispatch is authorized.

## Open work and dependencies

| Order | Workstream | GitHub issue | Status | Depends on |
|---:|---|---|---|---|
| 1 | Owner audit of prompt/schema contract | [#47](https://github.com/CarAutopsy/carautopsy/issues/47) | Open; owner human review and five-service AI cross-review evidence to record | Merged PR #43 |
| 2 | Retrieval/provenance security and zero-bypass acceptance | [#37](https://github.com/CarAutopsy/carautopsy/issues/37) | Open; owner security review, five-service AI cross-review, evidence reconciliation and source/activation gates | #49, #50, #52, #57–#72 |
| 3 | Owner review of exact source approvals | [#37](https://github.com/CarAutopsy/carautopsy/issues/37) | Pending any proposed source; exact host/URL and automated-access terms must be reviewed before manifest change | #37 |

Issue #44 (prompt builders and deterministic candidate gates) and #45 (no-retrieval safety stop) are closed. Their guarantees remain mandatory regression requirements.

## M1 — Owner audit of prompt/schema contract (#47)

- [ ] Pin exact merged PR #43 target SHA.
- [ ] Owner reads the specified documentation and schema-contract tests and records PASS / PASS WITH CONDITIONS / FAIL.
- [ ] Record findings, severity, rationale and required changes.
- [ ] Record the five AI cross-review services, actual model/version, exact-SHA confirmation, prompts/scope, findings, disagreements and residual risks.
- [ ] Confirm no live provider calls, source retrieval or factual vehicle-data verification occurred.
- [ ] Record scope limitations and PR #43 disposition.

## M2 — Retrieval, provenance and security acceptance (#37)

- [ ] Pin exact integrated source SHA and identify files/call paths under review.
- [ ] Owner performs and records a human security review covering SSRF/DNS pinning, TLS, URL parsing, robots/terms policy, extraction/parser safety, prompt injection, evidence semantics, candidate validation, auditor ordering, and retry/restart/state invariants.
- [ ] Cross-review with all five AI services already used by the project; record each service's exact SHA status, scope, findings, disagreements, unavailable/rate-limited reviews, unresolved risks and residual limitations.
- [ ] Run full Python tests, catalog validation, compilation, Repository Audit and exact-head workflows; record run URLs and SHA.
- [ ] Resolve findings and repeat affected checks against the new exact SHA.
- [ ] Keep technical acceptance gates: fail-closed source policy; DNS-pinned HTTPS; bounded extraction; traceable claim evidence; deterministic candidate gate before research auditors; two independent vendor PASS verdicts; no retry/restart bypass.
- [ ] Owner reviews each proposed exact host, source URL, relevance and automated-access terms before any manifest update.

## M3 — No-bypass and no-spend regression proof

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
