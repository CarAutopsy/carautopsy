# Current Project State

**Last updated:** 2026-11-20  
**Repository:** CarAutopsy/carautopsy  
**Default branch:** `main` (verified snapshot head `978a96c0dca4480e00528811ed4df18b49a6cdd8`)  
**Operating model:** one-person, zero-budget project; owner-led human review with AI cross-review

## Confirmed completed

- PR #43 merged: prompt/schema contract documentation and schema tests. The owner waived the audit prerequisite for that merge; the separate owner audit tracked by issue #47 is now CLOSED with PASS.
- PR #49 merged: schema-aligned prompt builders and deterministic candidate/evidence validation helpers.
- PR #50 merged: DNS-pinned HTTPS retrieval primitive.
- PR #52 merged: owner-controlled exact-host/URL policy, robots handling, bounded HTML/plain-text/PDF extraction, and claim-level quote/locator evidence bindings.
- PR #53's zero-bypass integration contract is on `main` through PR #56.
- PR #57 merged: runtime research orchestration wires retrieval preflight, evidence collection, researcher prompt, deterministic candidate validation, and two independent auditors behind the hard-disabled readiness gate.
- PRs #58–#60 merged: subprocess proofs for retrieval preflight, robots denial, and target-server failure without durable mutation.
- PRs #61–#63 merged: retry recovery, abrupt-interruption recovery, and cross-process state reconciliation proofs.
- PRs #64–#68 closed/merged or superseded as recorded in PR history; the final reconciliation follow-up exposes the public read-only `fetched_state_tip()` accessor while retaining the acknowledgment-enforcing `proposal_state_base()` API.
- PR #69 merged: Qodo review configuration for PR events, pushes, draft feedback, and bot-authored commit push reviews.
- PR #71 merged: owner-oriented security review handoff documentation.
- PR #72 merged: URL validation/redaction, full retrieval deadline enforcement, bounded robots-policy callback, response-length integrity checks, and regression tests.
- Issues #44 (prompt builders and deterministic candidate gates) and #45 (no-retrieval safety stop) are closed.
- Issue #47 is **CLOSED** with owner verdict **PASS** recorded 2026-11-13 for the PR #43 documentation/schema-contract audit at reviewed head `492390abec21ea268b22829f1017242d9b930121` (merge commit `647ff76af47c9f436b24e1bf5ad018962c8c91d3`). F-47-01 and F-47-02 were resolved (the latter via merged PR #73) and F-47-03 was informational. This did not authorize activation.
- Merged follow-ups after the previous reconciliation: #73–#74, #76–#81, #83–#85, #87–#93, #95–#96, #99–#103, #104–#113, #115–#117, #122 (evidence-bundle bounds regressions), #123 (structured-locator regressions), #125 (engineering-agent design proposal), #126 (TCO write-boundary review) and #128 (fixture-only pilot). #125, #126 and #128 merged at 15:36 UTC. Open at this snapshot: #124, #127, #130, #131 and #132, plus drafts #118 and #120.
- T-04 diagnostic URL path redaction is **implemented and merged** in PR #85 (2026-11-15, head `bf9c2f87729777074d11cae725d21c8589b88e23`); its post-merge integration still needs verification on the exact current SHA.
- Exact-head CI on snapshot main `978a96c`: Repository Audit [run #44765013835](https://github.com/CarAutopsy/carautopsy/actions/runs/44765013835) PASS; Validate Catalog [run #44765013903](https://github.com/CarAutopsy/carautopsy/actions/runs/44765013903) PASS. Earlier head `c3aad86` had Validate Catalog run 44747335215 PASS; `cf53dbd` had Validate Catalog run 44461265067 PASS, DeepSeek PR Auditor Tests run 44461264961 PASS, and paused-heartbeat Pipeline/Owner-Digest runs PASS (not data completion).

## Status vocabulary

- **Implemented:** change merged to `main` (for example #74–#89, #85, #87–#103, #122–#123).
- **Tested:** exact-head CI green for that SHA (snapshot `978a96c`: Repository Audit run 44765013835 and Validate Catalog run 44765013903 both PASS).
- **Accepted:** owner human verdict recorded at an exact SHA. Only #47 (PASS); #37 is **not accepted**.
- **Activated:** live retrieval / paid provider / dispatch authorized. **None** — manifest empty, readiness false, pause active. Implemented and tested never imply accepted or activated.

## Active Hive status

- Open acceptance issue: #37 (retrieval security/provenance review and activation gates). Issue #47 is closed with the owner PASS verdict recorded above.
- Also open: #86 (guarded issue-to-roadmap intake; draft PR #118 at `005028a` with step-1 regressions, exact-head CI PASS and independent audit requested), #114 (CivLab automation reuse extraction) and #119 (offline reconciliation/regression sprint).
- Runtime orchestration is integrated, but not production-enabled.
- `data-connectors/approved-source-hosts.json` intentionally has empty `approved_hosts` and `source_policies` arrays.
- `VERIFIED_RETRIEVAL_AVAILABLE = False` (`scripts/autonomous_pipeline.py:168`); `HIVE_RESEARCH_PAUSED` remains active.
- The scheduled `autonomous-pipeline.yml` heartbeat (`7,22,37,52 * * * *`) and crawler-only dispatch are read-only/paused-path activity. They are not evidence of live data completion or source permission.
- Full TCO mode remains separate from Hive research; provider smoke-test routing remains separate.
- No live OEM retrieval, paid research calls, or vehicle research dispatch is authorized.
- The vehicle queue and failed-candidate ledger remain quarantined while research is paused. Do not automatically retry or promote failed records.

## Required owner review and AI cross-review

This is a one-person, zero-budget project. No paid external auditor is required. The project owner performs and records the human review. The five AI services already used by the project provide supplementary cross-review; they do not replace the owner's judgment.

For #37, record each AI service's findings, disagreements, unresolved risks, and residual limitations alongside the owner's review of the exact audited SHA. Retain the technical acceptance requirements: fail-closed policy, DNS-pinned HTTPS, bounded extraction, evidence traceability, deterministic candidate gate, two independent vendor PASS verdicts, and no retry/restart bypass.

For #47, the owner PASS verdict, exact SHA, disposition of findings and available cross-review evidence are already recorded in the issue; no further #47 acceptance work is required.

## Remaining acceptance work

1. **Pin first:** verify the post-merge integration of PR #85 (T-04 diagnostic URL path redaction) on the exact current main SHA and record the integrated head that #37 will review.
2. Complete and record the owner security review for #37 against **that pinned SHA**. Record cross-review from all five AI services, material disagreements, unresolved risks, and residual limitations. Re-pin and repeat affected checks if the head changes before the verdict.
3. Have the owner review each proposed exact OEM/official hostname, exact URL, source relevance, and automated-access terms before any manifest entry is added.
4. Resolve review findings and run exact-head CI/security validation (including Repository Audit on the exact final SHA).
5. Complete the no-bypass regression gaps tracked in #119 without changing production gates.
6. Only after all acceptance criteria are met, obtain explicit owner authorization before considering retrieval activation.

See [ROADMAP.md](ROADMAP.md), [NEXT_ACTIONS.md](NEXT_ACTIONS.md), and [HIVE_PIPELINE_INTEGRATION.md](HIVE_PIPELINE_INTEGRATION.md).

## Operational constraints

- Do not add hosts or exact URLs to the approved manifest without owner review.
- Do not treat a green heartbeat, a successful crawler-only run, or a generated proposal artifact as verified data, source permission, or an owner decision.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove the research pause as part of intermediate implementation PRs.
- Do not use live source requests or paid provider calls in unit/CI tests.
- Do not treat schema validity, quote presence, or HTTP 2xx as proof that a vehicle claim is true.
- Preserve two independent vendor PASS verdicts for candidate acceptance; this vendor gate is distinct from the five-service AI cross-review used for security review.
- AI review output is advisory evidence; the owner records the final human verdict.
