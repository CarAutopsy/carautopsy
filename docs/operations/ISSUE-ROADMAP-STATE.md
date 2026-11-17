# Canonical issue-roadmap state

The reconciliation workflow uses `docs/operations/issue-roadmap-state.json` as
its canonical, owner-maintained task mapping. It is intentionally separate from
the narrative Hive roadmap in `ROADMAP.md`.

## Schema

The top-level object contains exactly:

- `schema_version`: integer `1`;
- `repository`: `CarAutopsy/carautopsy`;
- `tasks`: an array of explicitly mapped issue tasks.

Each task contains exactly:

- `task_key`: stable lowercase slug, normally `issue-N`;
- `issue_number`: unique positive GitHub issue number;
- `status`: current owner-maintained status (`proposed`, `approved`,
  `blocked`, `in_progress`, `done`, or `needs-owner-triage`);
- `dependencies`: unique task keys that must already be `done`;
- `source_updated_at`: timezone-aware GitHub issue `updated_at` observed
  when the owner last reconciled this task.

The initial file has an empty task list. This is deliberate: no task mapping,
status, dependency, or timestamp is inferred from prose, labels, AI output, or
the existence of a PR. Populate entries only after the owner explicitly decides
which issues are tracked roadmap tasks and records their current status and
issue timestamp.

## Workflow behavior

The existing scheduled crawler still classifies all issue states. The
reconciliation adapter then selects only issue snapshots whose numbers are
explicitly present in this file. Unmapped issues are excluded from PR timeline
and check-run collection.

The evidence collector uses GitHub issue timeline cross-reference events,
canonical PR metadata, and check runs for each exact PR head SHA. The workflow
publishes a deterministic `issue-roadmap-reconciliation-proposal` artifact
for seven days. All status changes remain pending owner approval; no workflow
step applies the proposal.

When an issue changes, the snapshot timestamp becomes stale. The report
preserves the current status and asks for an owner-reviewed snapshot refresh
before proposing a transition. Do not update `source_updated_at` merely to
silence a stale warning.

## Safety boundary

- The job has read-only `contents`, `issues`, `pull-requests`, and
  `checks` permissions.
- It creates no branches, commits, labels, comments, PRs, roadmap changes, or
  task dispatches.
- It does not read issue or PR bodies/comments for linkage or status evidence.
- It does not accept approval manifests or infer owner approval.
- Hive remains paused; source manifests, OEM access, paid providers, queues,
  and readiness activation remain outside this workflow.
