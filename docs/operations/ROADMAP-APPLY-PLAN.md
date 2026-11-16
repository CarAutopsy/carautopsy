# Owner-approved roadmap apply plan

`scripts/issue_roadmap_apply.py` builds a deterministic apply plan from the crawler's
all-state dry-run report. It does not write files, call GitHub, post comments, or dispatch tasks.

## Required approval manifest

The manifest is bound to:

- the exact canonical digest of the full crawler report;
- the repository and authenticated owner login;
- the GitHub blob SHA of `docs/operations/ROADMAP.md` observed when the owner approved;
- a timezone-aware approval timestamp and the explicit confirmation phrase
  `APPLY ROADMAP PROPOSAL`;
- an explicit list of actionable open issue proposals, with owner-supplied acceptance
  criteria and dependencies.

The apply planner rejects stale roadmap SHAs, duplicate/ambiguous issue snapshots, closed
issues, triage-only proposals, missing acceptance criteria, unknown dependencies, dependency
cycles, and task-key collisions. Only `issue-N` keys from actionable proposals can be approved.

## Idempotency and tamper detection

Applied proposal digests and task records are stored in a controller-managed block in
`ROADMAP.md`. The planner verifies that block has not been edited outside the controller.
Reapplying the same exact proposal is a no-op; a reused task key with different content fails.

## Caller requirements

A future workflow must pass the authenticated `github.actor` as
`expected_owner_login`, fetch the current roadmap blob SHA from GitHub, and rerun the
read-only crawler immediately before planning. The approval manifest alone is not an
authentication mechanism.

This PR only adds the pure planner and tests. A separate owner-authorized workflow PR is
required before any roadmap write can occur. That workflow must remain disabled unless an
explicit repository setting enables it and must use a protected environment. No task queue,
owner policy, Hive gate, source manifest, provider, OEM, or readiness state is in scope.
