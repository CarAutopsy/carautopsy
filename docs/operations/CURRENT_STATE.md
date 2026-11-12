# Current Project State

**Last updated:** 2026-11-12  
**Repository:** CarAutopsy/carautopsy  
**Default branch:** `main`  
**Current mode:** GitHub + GitHub Actions development

## Confirmed completed

- PR #43 merged to `main`: prompt/schema contract documentation and schema tests. The owner explicitly waived the independent-audit prerequisite for that merge; the waiver did not satisfy issue #47.
- PR #49 merged: schema-aligned prompt builders and deterministic candidate/evidence validation helpers. Runtime orchestration wiring remains incomplete.
- PR #50 merged: DNS-pinned HTTPS retrieval primitive.
- PR #52 merged to `main`: owner-controlled source policy checks, robots handling, bounded extraction workers, and claim-level quote/locator evidence bindings.
- PR #53 merged into `feat/hive-source-policy-extraction`, not directly into `main`. Its zero-bypass integration contract is being copied to `main` in the roadmap reconciliation PR.
- Issue #45 (no-retrieval safety stop) is closed; its invariants remain mandatory.

## Active Hive status

- Open issues: #37 (retrieval/provenance/runtime integration), #44 (candidate gate/prompt integration reconciliation), #47 (independent third-party audit).
- Retrieval and evidence helpers are isolated building blocks. They are not proof that the live pipeline invokes them before paid auditors.
- `data-connectors/approved-source-hosts.json` has an empty approved-host and source-policy list.
- `VERIFIED_RETRIEVAL_AVAILABLE = False`; `HIVE_RESEARCH_PAUSED` remains active.
- No live OEM retrieval, paid provider calls, or vehicle research dispatch is authorized.
- The vehicle queue has 23 variants; failed candidate/audit records remain in `tasks/failed.json`. Do not automatically retry or promote them while paused.

## Immediate engineering sequence

1. Merge the documentation-only roadmap reconciliation PR.
2. Reconcile #44's scope against the merged #49 helper implementation.
3. Implement the shared retrieval → prompt → deterministic gate orchestration seam before any auditor invocation.
4. Prove zero-bypass, zero-spend, and no-state-mutation behavior across failures, retries, and restarts.
5. Complete independent external review and obtain explicit owner authorization before considering activation.

See [ROADMAP.md](ROADMAP.md), [NEXT_ACTIONS.md](NEXT_ACTIONS.md), and [HIVE_PIPELINE_INTEGRATION.md](HIVE_PIPELINE_INTEGRATION.md).

## Operational constraints

- Do not add hosts or exact URLs to the approved manifest without owner review.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove the research pause as part of intermediate implementation PRs.
- Do not use paid provider calls or live source requests in unit/CI tests.
- Do not treat schema validity, quote presence, or HTTP 2xx as proof that a vehicle claim is true.
- Preserve two independent vendor PASS verdicts and required human review.
