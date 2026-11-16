# Issue roadmap crawler

The `issue-roadmap-crawler` job is a read-only intake monitor attached to the existing
`autonomous-pipeline.yml` schedule. It does not introduce a second scheduler.

## Operation

- Runs whenever the existing autonomous pipeline schedule fires (currently every 15 minutes).
- Can also be started manually with the `crawler-only` workflow-dispatch mode.
- Reads open GitHub issue metadata using the run-scoped `GITHUB_TOKEN`.
- Projects issue snapshots to a strict metadata allowlist; issue bodies and comments are not
  interpreted or retained.
- Classifies only from maintainer-controlled `roadmap:*` labels and basic issue metadata.
- Uploads deterministic JSON as the `issue-roadmap-dry-run` artifact for seven days and
  writes a short count summary to the Actions run summary.

## Safety boundary

This job has only `contents: read` and `issues: read` permissions. It does not:

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

Download the `issue-roadmap-dry-run` artifact from the run to inspect the complete JSON report.
