# Issue roadmap crawler

The `issue-roadmap-crawler` job is a read-only intake monitor attached to the existing
`autonomous-pipeline.yml` schedule. It does not introduce a second scheduler.

## Operation

- Runs whenever the existing autonomous pipeline schedule fires (currently every 15 minutes). It can also be started manually with crawler-only.
- Can also be started manually with the `crawler-only` workflow-dispatch mode.
- Reads all GitHub issue states (open and closed) using the run-scoped `GITHUB_TOKEN`.
- The controller supports `--state open`, `--state closed`, and `--state all`; the scheduled crawler uses `--state all`.
- Projects issue snapshots to a strict metadata allowlist; issue bodies and comments are not
  interpreted or retained.
- Classifies only from maintainer-controlled `roadmap:*` labels and basic issue metadata.
- Uploads deterministic JSON, including minimal per-issue number/state/updated_at evidence, as the
  `issue-roadmap-dry-run` artifact for seven days. It then reconciles only issues explicitly mapped
  in `issue-roadmap-state.json`, collects linked PR and exact-head check evidence, and uploads the
  owner-gated `issue-roadmap-reconciliation-proposal` artifact for seven days.

## Safety boundary

This job has only `contents: read`, `issues: read`, `pull-requests: read`, and
`checks: read` permissions. It does not:

- create or edit issues, labels, comments, pull requests, branches, or roadmap files;
- read pull-request or CI evidence or infer task completion;
- dispatch, reserve, generate, or publish tasks;
- modify `tasks/queue.json`, `tasks/failed.json`, owner policy, Hive gates, or source manifests;
- call AI providers, access OEM sources, or activate research/readiness.

Every actionable classification remains a proposal requiring owner review. Unknown or conflicting
labels remain owner-triage; issue text is untrusted and cannot authorize a status or policy change.

## Manual run

In GitHub Actions, run **Autonomous Pipeline (Hive Research + TCO)** with
`run_mode=crawler-only`. The crawler job runs without entering the Hive research or TCO steps.

Download `issue-roadmap-dry-run` for all-state classification and `issue-roadmap-reconciliation-proposal`
for the deterministic status proposal and exact PR/CI evidence. Only explicitly mapped tasks are reconciled.
