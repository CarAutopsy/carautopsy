# Roadmap reconciliation — proposal-only contract

**Scope:** Issue #86 implementation slice. This module validates a structured roadmap snapshot and creates status-change proposals from projected GitHub evidence. It does not apply changes.

## Inputs

- Roadmap tasks: stable `task_key`, unique `issue_number`, current `status`, dependency task keys, and the last reconciled `source_updated_at`.
- Issue snapshots: GitHub issue number, open/closed state, and `updated_at`. Issue bodies and comments are not accepted.
- Linked PR evidence: PR metadata plus an explicit `github-cross-reference-event` marker produced only by a future GitHub timeline collector. PR body text, issue text, labels, and AI claims are not linkage evidence.
- Check runs: name, conclusion, and exact `head_sha`. A successful check on another SHA does not count.
- `approved_task_keys`: an explicit owner-supplied set. Without it, all proposed status changes remain pending owner approval.

## Status evidence rules

- An open issue with a GitHub cross-referenced open PR may propose `in_progress`.
- A closed issue may propose `done` only when its linked PR is merged, the merge commit SHA is valid, and the `audit` (Repository Audit) and `validate` (Validate Catalog) check-runs succeeded on the exact PR head SHA.
- A merged PR with an issue still open, or a closed issue with an open PR, is sent to owner triage.
- Missing issue/PR/check evidence preserves the current roadmap status. An issue being closed or a PR merely being opened never proves completion.
- A newer GitHub `updated_at` than the roadmap's `source_updated_at` marks the record stale and blocks a status proposal until the roadmap snapshot is refreshed.
- Dependencies must exist, be unique, and form an acyclic graph. A task cannot advance while any dependency is not `done`.

## Safety and non-goals

- Output is deterministic and proposal-only; no roadmap, GitHub, workflow, label, comment, or task-queue writes occur.
- No automatic apply path is included in this slice. Any future apply path must consume an explicit owner approval and revalidate the source evidence immediately before writing.
- GitHub evidence must be collected from API metadata/timeline/check-run endpoints by a separate bounded read-only collector. This pure module does not authenticate GitHub claims or fetch data.
- The controller does not introduce a scheduler and does not change the existing 15-minute autonomous pipeline.
- Hive remains paused. No source-manifest change, live retrieval, OEM access, provider call, queue dispatch, or readiness activation is permitted.

## Tests

`tests/test_issue_roadmap_sync.py` covers exact-SHA checks, owner approval, stale snapshots, missing evidence, dependency readiness, duplicate IDs, dependency cycles, malformed PR evidence, input immutability, and deterministic output.
