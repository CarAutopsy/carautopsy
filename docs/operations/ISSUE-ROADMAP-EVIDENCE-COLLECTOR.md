# Live roadmap evidence collector

`scripts/issue_roadmap_evidence.py` is the read-only transport layer for
`scripts/issue_roadmap_sync.py`.

## Evidence contract

- Accepts only projected issue records (`number`, `state`, `updated_at`) and a
  separately supplied structured roadmap task list.
- Uses the GitHub issue timeline API and accepts linkage only from
  `cross-referenced` events whose source issue contains a pull-request marker
  and a canonical `repository_url` (or structured `repository.full_name`) matching the configured repository.
  Cross-repository references are ignored; missing or malformed repository
  identity fails closed.
- Fetches PR state, merged state, head SHA, and merge commit SHA from the PR API.
- Fetches check runs once per distinct PR head SHA (even when several PRs share
  that commit), independently verifies every returned check run's own `head_sha`
  against the requested PR head, and projects
  only check ID, name, conclusion, exact head SHA, and run URL.
- Bounds issue, PR, page, and check-run counts; validates pagination hosts,
  endpoint paths, and sequential page numbers; sanitizes request failures.
- Emits a deterministic proposal-only reconciliation report to stdout.

Issue/PR bodies, comments, labels, and AI-generated claims are never used as
linkage or completion evidence. The collector performs no writes, does not
self-approve tasks, and cannot activate task dispatch or research.

## Input contract

The JSON input contains `repository`, `roadmap_tasks`, and `issue_snapshots`.
Each issue snapshot must contain only `number`, `state`, and timezone-aware
`updated_at`. Roadmap tasks use the schema documented in
`ISSUE_ROADMAP_RECONCILIATION.md`. Owner approvals are deliberately absent
from the live collector input.

The collector is enabled in the existing 15-minute crawler job as a read-only
reconciliation stage. Its issue scope is restricted to tasks explicitly mapped
in `docs/operations/issue-roadmap-state.json`; an empty mapping produces an
empty, deterministic proposal without timeline or PR lookups. The workflow
publishes the full deterministic proposal JSON as the
`issue-roadmap-reconciliation-proposal` artifact for seven days. The separate
owner-authorized apply path remains disabled and requires its own explicit
decision and protected workflow.
