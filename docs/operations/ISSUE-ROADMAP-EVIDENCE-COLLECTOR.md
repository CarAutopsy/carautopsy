# Live roadmap evidence collector

`scripts/issue_roadmap_evidence.py` is the read-only transport layer for
`scripts/issue_roadmap_sync.py`.

## Evidence contract

- Accepts only projected issue records (`number`, `state`, `updated_at`) and a
  separately supplied structured roadmap task list.
- Uses the GitHub issue timeline API and accepts linkage only from
  `cross-referenced` events whose source issue contains a pull-request marker.
- Fetches PR state, merged state, head SHA, and merge commit SHA from the PR API.
- Fetches check runs for each distinct PR head SHA and projects only check ID,
  name, conclusion, exact head SHA, and run URL.
- Bounds issue, PR, page, and check-run counts; validates pagination hosts,
  endpoint paths, and sequential page numbers; sanitizes request failures.
- Emits a deterministic proposal-only reconciliation report to stdout.

Issue/PR bodies, comments, labels, and AI-generated claims are never read as
linkage or completion evidence. The collector performs no writes, does not
self-approve tasks, and cannot activate task dispatch or research.

## Input contract

The JSON input contains `repository`, `roadmap_tasks`, and `issue_snapshots`.
Each issue snapshot must contain only `number`, `state`, and timezone-aware
`updated_at`. Roadmap tasks use the schema documented in
`ISSUE_ROADMAP_RECONCILIATION.md`. Owner approvals are deliberately absent
from the live collector input.

The collector is a separately testable component. It is not yet enabled in the
15-minute workflow: that integration requires a reviewed, canonical structured
roadmap task source and a separate owner decision for any write-capable workflow.
