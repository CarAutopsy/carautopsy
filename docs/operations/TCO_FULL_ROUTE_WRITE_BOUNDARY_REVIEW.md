# TCO `full` route direct-to-main write boundary — review findings

**Status:** Findings-only review. No workflow, script, policy or gate change is made by this document.
**Tracking:** issue #114 (CivLab reuse assessment §5.3 / §7), issue #37 (activation gates).
**Baseline reviewed:** CarAutopsy `main` at `cf53dbd142729c80c2ce45bfa38d294482a99fe4`.
**Date:** 2026-11-20.

The CivLab reuse assessment flagged the manually dispatched `full` TCO route as an adjacent write boundary to review separately before expanding automation. This document records that review. It does not authorize a change, and it does not affect the paused Hive research route.

## 1. Scope and evidence

Reviewed files at the baseline SHA:

- `.github/workflows/autonomous-pipeline.yml` — job graph, triggers, permissions, checkout settings.
- `scripts/autonomous_pipeline.py` — mode selection, catalog gate, publication and git write path.

Methods: static source inspection and the existing workflow contract tests (`tests/test_autonomous_pipeline_workflow.py`, PR #124). No workflow was dispatched, no live source or provider call was made, and no repository state was written.

## 2. Confirmed facts

1. **Manual-only entry.** The `full` route runs only under `workflow_dispatch` with `inputs.run_mode == 'full'` (`autonomous-pipeline.yml` step `Gated TCO pipeline`). It is not reachable from the 15-minute schedule or from `crawler-only`.
2. **Research gate is intentionally bypassed.** `RESEARCH_ONLY = "--research-only" in sys.argv` (`autonomous_pipeline.py:163`). `require_verified_retrieval(VERIFIED_RETRIEVAL_AVAILABLE)` and the empty-source-policy check are executed only under `RESEARCH_ONLY` (`:173-181`). The research-only path ends with `sys.exit(0)` at `:636`, so it never reaches the TCO publication block. This is separate from the paused Hive route; it is not evidence that Hive is active.
3. **Fail-closed catalog gate exists.** Before calculation, the full route loads the country config, calls `assert_tax_pack_publishable`, and blocks publication when `validate_catalog_readiness` returns findings (`:187-199`). A calculation error aborts the whole result set rather than publishing partial output (`:640-644`).
4. **Direct write to main.** The publication block writes `apps/web/public/data/autopsies.json` (`:666-678`), then runs `git add -A`, `git commit`, and `git push origin main` (`:688-693`).
5. **Broad staging scope.** Unlike the research-only path, which stages an explicit list (`git add catalog/variants tasks/queue.json tasks/failed.json`, `:593`), the full route stages the **entire working tree** with `git add -A` (`:690`).
6. **Job permissions**. The `run` job has `contents: write` and `pull-requests: write`; checkout uses `fetch-depth: 0` and `persist-credentials: true` (`autonomous-pipeline.yml:28-53`). The crawler job is read-only.
7. **Failure behavior.** After pushing, a run with `audit_failures_this_run` exits 1 (`:694-696`), so the workflow can be red while the main-branch write has already happened.
8. **No publication attestation.** The published payload contains a generated UTC timestamp (`:658`) but no artifact digest, base SHA, or owner-approval marker binding the write to a reviewed input snapshot.

## 3. Risk assessment

| Finding | Risk | Severity |
|---|---|---|
| `git add -A` stages every dirty file in the runner checkout | Any unrelated or transient file present at checkout is committed and pushed to `main` | Medium |
| `pull-requests: write` granted to the same job that pushes to `main` | Broader than required for TCO publication; a defect in the research branches of the same script could use it | Medium |
| No digest/base-SHA attestation on the published artifact | Reviewers cannot bind the published data to the exact catalog/tax inputs that produced it | Low / Medium |
| Push occurs before the run's failure exit | A red workflow does not imply the write was withheld | Low |
| Manual-only trigger and fail-closed catalog gate | Limits accidental/scheduled execution and blocks unpublishable catalogs | Mitigating |

**Not demonstrated:** live retrieval, provider spend, source-manifest mutation, queue dispatch, or Hive activation on this route. The research pause (`VERIFIED_RETRIEVAL_AVAILABLE = False`, empty approved-source manifest) is unchanged.

## 4. Recommendations (proposals only; none applied)

1. Replace `git add -A` with an explicit path list containing only `apps/web/public/data/autopsies.json`, and fail closed if unrelated tracked changes exist before the write.
2. Split publication into its own least-privilege job with `contents: write` only; keep `pull-requests: write` confined to the research-PR job. Pin this split with static workflow contract tests in the style of PR #124.
3. Add an artifact attestation: base SHA, catalog digest, tax-pack version and run URL in the payload, plus a regression test that the digest matches the inputs.
4. Prefer an owner-reviewed draft PR over a direct push to `main` for generated data, consistent with the engineering-agent design proposal (PR #125).
5. Move the audit-failure exit before the write so a failing run cannot publish, and add a test proving no push occurs on that path.

## 5. Owner decisions required

- Whether to narrow the write scope and split job permissions (Recommended).
- Whether generated TCO data should continue to go directly to `main` or move to a draft-PR gate.
- Whether any change here is in scope before #37 acceptance is complete.

This review records no verdict on owner acceptance and authorizes no activation, spend, merge or workflow dispatch.
