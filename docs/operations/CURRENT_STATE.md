# Current Project State

**Last updated:** 2026-11-22  
**Repository:** CarAutopsy/carautopsy  
**Default branch:** `main`  
**Operating model:** one-person, zero-budget project; owner-led human review with AI cross-review

## Confirmed completed

- PR #43 merged: prompt/schema contract documentation and schema tests. The owner waived the audit prerequisite for that merge; issue #47 is closed with owner PASS at reviewed PR #43 head `492390abec21ea268b22829f1017242d9b930121`.
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
- PR #141 merged: offline EEA evidence harvester plus identity/price research layer. [TRACE_EXECUTION]
- PR #142 merged: catalog batch 001 — 95 owner-approved 2018 Austrian variants. [TRACE_EXECUTION]
- PR #143 merged: catalog batch 002 — 19 owner-approved 2018 Austrian Fabia variants. [TRACE_EXECUTION]
- PR #140 merged: offline catalog quality, completeness and refresh planner. [TRACE_EXECUTION]
- PR #145 merged: offline bulk catalog ingestion with dry-run, staging and idempotence. [TRACE_EXECUTION]
- Documentation state reconciled on 2026-11-22 to exact HEAD `245f8fdf676e855860e838413838a9d3b52f900c`; see `.carautopsy/sessions/CARAUTOPSY-SESSION-OPENCODE-20261122-0502-001.md`. [TRACE_EXECUTION]

## Offline catalog and ingestion workstream (2026-11-21)

- `catalog/variants/` now holds 120 records. Measured at HEAD `245f8fd` with
  `--now 2026-11-22T09:00:00Z`: 0 structural errors, 0 blocking findings,
  overall completeness 0.2633, all refresh-plan entries P1 with
  `network_permitted: false`. [TRACE_EXECUTION]
- Most new EEA-sourced records lack `identity.model_year_from`,
  `performance.power_w`, `dimensions.curb_mass_kg` and offer/price fields, so
  completeness fell against the earlier 6-variant baseline (0.3287). These are
  tool-quality metrics, not verified vehicle data. [REASONED_ONLY]
- `scripts/ingest_bulk_catalog.py` is offline and fails closed: catalog-shaped
  records are staged only in a branch-scoped `staging/` directory, with no write
  to `catalog/variants/`, no network and no secrets. The separate required
  `--report` file is written even in dry-run mode, may target a path outside
  `staging/` (except under `catalog/variants/`), and can overwrite an existing
  file; operators must choose a safe temporary report path. [STATIC_READ]
- In the 2018 AT sample, 114 rows resolve to identities already in the catalog
  and are correctly reported as duplicates with zero new staging records; the
  other 40 rows are rejected before duplicate detection because verified price
  evidence is unavailable. [TRACE_EXECUTION]
- Draft PR #144 (`copilot/build-ingest-bulk-catalog-script`) remains open and
  overlaps the scope merged in #145; disposition is an owner decision. [TRACE_EXECUTION]

## Active Hive status
 
- Open acceptance issues: #37 (retrieval security/provenance review and activation gates) and #47 (owner human audit of prompt-overhaul docs/schema tests).
- Runtime orchestration is integrated, but not production-enabled.
- `data-connectors/approved-source-hosts.json` intentionally has empty `approved_hosts` and `source_policies` arrays.
- `VERIFIED_RETRIEVAL_AVAILABLE = False`; `HIVE_RESEARCH_PAUSED` remains active.
- Full TCO mode remains separate from Hive research; provider smoke-test routing remains separate.
- No live OEM retrieval, paid research calls, or vehicle research dispatch is authorized.
- The offline catalog/ingestion workstream did not change any Hive readiness, source-manifest, catalog-write or activation gate. [OWNER_DECISION]
- The vehicle queue and failed-candidate ledger remain quarantined while research is paused. Do not automatically retry or promote failed records.

## Required owner review and AI cross-review

This is a one-person, zero-budget project. No paid external auditor is required. The project owner performs and records the human review. The five AI services already used by the project provide supplementary cross-review; they do not replace the owner's judgment.

For #37, record each AI service's findings, disagreements, unresolved risks, and residual limitations alongside the owner's review of the exact audited SHA. Retain the technical acceptance requirements: fail-closed policy, DNS-pinned HTTPS, bounded extraction, evidence traceability, deterministic candidate gate, two independent vendor PASS verdicts, and no retry/restart bypass.

For #47, the owner audits the exact PR #43 merged target and records verdict, findings, exact SHA, the five AI cross-reviews, and the required no-live-activity/scope limitations.

## Remaining acceptance work

1. Complete and record the owner human audit for #47 against the exact commit specified in that issue.
2. Complete and record the owner security review for #37 against the integrated retrieval/orchestration code. Record cross-review from all five AI services, material disagreements, unresolved risks, and residual limitations.
3. Have the owner review each proposed exact OEM/official hostname, exact URL, source relevance, and automated-access terms before any manifest entry is added.
4. Resolve review findings and run exact-head CI/security validation.
5. Only after all acceptance criteria are met, obtain explicit owner authorization before considering retrieval activation.

See [ROADMAP.md](ROADMAP.md), [NEXT_ACTIONS.md](NEXT_ACTIONS.md), and [HIVE_PIPELINE_INTEGRATION.md](HIVE_PIPELINE_INTEGRATION.md).

## Operational constraints

- Do not add hosts or exact URLs to the approved manifest without owner review.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove the research pause as part of intermediate implementation PRs.
- Do not use live source requests or paid provider calls in unit/CI tests.
- Do not treat schema validity, quote presence, or HTTP 2xx as proof that a vehicle claim is true.
- Preserve two independent vendor PASS verdicts for candidate acceptance; this vendor gate is distinct from the five-service AI cross-review used for security review.
- AI review output is advisory evidence; the owner records the final human verdict.

## Static backlog checkpoint (2026-11-25)

PRs #118, #121, #133 and #144 are closed without merge. PR #85 merged at `d3d6188134a8fa1bf5a1046b36dc8e21f139e8cf` (reviewed head `bf9c2f87729777074d11cae725d21c8589b88e23`). #130/#135/#138 merged; #168 addresses an additional publication-path defect. #113 merged at `09f590f41f9db02d48b40fa45d65b78364b8a864`; live crawler-only execution evidence still required for #86. Historical measurements above remain pinned to their original SHA and date. Copilot retired; no new assignments. No test or activation claim.
