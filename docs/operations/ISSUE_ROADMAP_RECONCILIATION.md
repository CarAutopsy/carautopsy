# Roadmap reconciliation — proposal-only contract

**Scope:** Issue #86 implementation slice. This module validates a structured roadmap snapshot and creates status-change proposals from projected GitHub evidence. It does not apply changes.

## Inputs

- Roadmap tasks: stable `task_key`, unique `issue_number`, current `status`, dependency task keys, and the last reconciled `source_updated_at`.
- Issue snapshots: GitHub issue number, open/closed state, and `updated_at`. Issue bodies and comments are not accepted.
- Linked PR evidence: PR metadata plus an explicit `github-cross-reference-event` marker produced only by a future GitHub timeline collector. PR body text, issue text, labels, and AI claims are not linkage evidence.
- Check runs: name, conclusion, and exact `head_sha`. A successful check on another SHA does not count; duplicate required check-runs on the same SHA are treated as ambiguous and block completion.
- `approved_task_keys`: an explicit owner-supplied set. Without it, all proposed status changes remain pending owner approval.

## Status evidence rules

- An open issue with a GitHub cross-referenced open PR may propose `in_progress`.
- A closed issue may propose `done` only when its linked PR is merged, the merge commit SHA is valid, and the mandatory `audit` (Repository Audit) and `validate` (Validate Catalog) check-runs succeeded exactly once on the PR head SHA. Callers may add checks but cannot remove either mandatory check. The validated merge commit SHA is included in the proposal evidence.
- A merged PR with an issue still open is sent to owner triage even when CI evidence is missing or ambiguous. A closed issue with an open PR is also sent to owner triage. Reopened issues therefore cannot be proposed as done.
- Missing issue/PR evidence preserves the current roadmap status. Missing or ambiguous CI evidence blocks `done`, but does not suppress owner triage for an open issue with a merged PR. An issue being closed or a PR merely being opened never proves completion.
- Any mismatch between GitHub `updated_at` and the roadmap's `source_updated_at` (including a future roadmap timestamp) marks the record stale and blocks a status proposal until the roadmap snapshot is refreshed.
- Dependencies must exist, be unique, and form an acyclic graph. A task cannot advance while any dependency is not `done`.

## Safety and non-goals

- Output is deterministic and proposal-only; no roadmap, GitHub, workflow, label, comment, or task-queue writes occur.
- No automatic apply path is included in this slice. Any future apply path must consume an explicit owner approval and revalidate the source evidence immediately before writing.
- GitHub evidence is collected by the bounded read-only `issue_roadmap_evidence.py` collector from API metadata, timeline, and exact-head check-run endpoints. The collector is wired to the existing schedule and receives only issues explicitly mapped in `issue-roadmap-state.json`. This pure module does not authenticate GitHub claims or fetch data.
- The controller does not introduce a scheduler and does not change the existing 15-minute autonomous pipeline.
- Hive remains paused. No source-manifest change, live retrieval, OEM access, provider call, queue dispatch, or readiness activation is permitted.

## Tests

`tests/test_issue_roadmap_sync.py` covers exact-SHA checks, owner approval, stale snapshots, missing evidence, dependency readiness, duplicate IDs, dependency cycles, malformed PR evidence, input immutability, and deterministic output.
