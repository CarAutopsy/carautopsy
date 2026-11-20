# CarAutopsy roadmap evidence reconciliation — 2026-11-20

Status: **review checklist; no activation or acceptance claim**. Related: issue #119.

## Evidence hierarchy

GitHub issue state and owner acceptance comments are authoritative for decisions; merged commits and exact-SHA workflow runs are authoritative for implemented code and CI. The roadmap and handover documents are derived summaries and must not override either.

## Verified from repository inspection

- At this checkpoint PR #118 was the only open PR, a draft WIP with zero changed files at head `0afac78c5244e39fbb12f4fb5d4f8419f1c971a5`. It is not merge-ready.
- `docs/operations/ROADMAP.md`, `CURRENT_STATE.md` and `NEXT_ACTIONS.md` all identify 2026-11-13 as their latest reconciliation/update date; re-check issues #37, #47 and #86 against newer records before updating their acceptance state.
- `.github/workflows/autonomous-pipeline.yml` contains the cron expression `7,22,37,52 * * * *`, a `crawler-only` dispatch mode and a research-pause preflight. Workflow configuration does not establish successful execution.
- `docs/operations/HIVE_ISSUE_37_ACCEPTANCE.md` describes the review and source activation gates and explicitly says its evidence record is not activation approval.

## Required evidence collection

1. **Issue #86 / PR #118:** check classification/reconciliation contract, real diff, exact-head CI, owner-reviewed findings and remaining offline tests.
2. **Crawler-only proof:** identify a workflow run URL, exact SHA, successful job result, artifact name `issue-roadmap-reconciliation-proposal`, artifact contents/schema and whether the run performed any mutation. Mark unavailable if evidence cannot be inspected.
3. **Issue #47:** inspect the actual owner verdict and recorded SHA. Do not assume open/closed state from the dated roadmap.
4. **Issue #37:** reconcile current owner security verdict, independent AI reviews, residual findings, source-host manifest and activation decision. Keep technical acceptance separate from activation.
5. **Post-merge checks:** inspect current `main` workflows and any new CI requirements. Do not reuse a PR-head PASS as a main-branch verification without checking.
6. **Roadmap update:** update `ROADMAP.md`, `CURRENT_STATE.md`, `NEXT_ACTIONS.md` together only after the above evidence is pinned, noting measured vs unmeasured outcomes.

## Non-negotiable safety boundaries

- Keep `VERIFIED_RETRIEVAL_AVAILABLE = False`, research paused and the owner-controlled approved-source manifest empty pending separate authorization.
- No live OEM retrieval, paid provider requests, automatic promotion of rejected candidates, or autonomous merges.
- A green heartbeat or successful crawler-only run is not proof of database population, source permission or verified vehicle claims.
- Owner alone approves merges and activation.

## Next 72 hours

- **Day 1:** finish PR #118 offline regressions; gather crawler and issue evidence; open a separate exact-source roadmap correction PR.
- **Day 2:** fill demonstrated no-bypass regression gaps, including malformed metadata, idempotency, restart and no-mutation behavior.
- **Day 3:** prepare legal/source approval dossiers and a tiny synthetic pilot plan; do not run live retrieval or spend money.

Record evidence links, exact SHAs, observed check conclusions, owner decisions and unresolved blockers in issue #119.
