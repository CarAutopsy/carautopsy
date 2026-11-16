# GitHub issue roadmap intake — dry-run controller

The issue intake controller is deliberately read-only. It consumes GitHub issue
metadata or a local JSON fixture, applies the pure classifier in
`scripts/issue_roadmap.py`, and emits a deterministic JSON proposal artifact
to standard output. The report includes snapshot classification counts so
informational, blocked, and duplicate issues remain visible even though they
do not become proposals.

## Run with the example fixture

```bash
python scripts/issue_roadmap_controller.py --input tests/fixtures/issue-intake.example.json
```

To save a report outside the repository, redirect standard output:

```bash
python scripts/issue_roadmap_controller.py --input tests/fixtures/issue-intake.example.json > /tmp/issue-roadmap-proposals.json
```

A fixture may be a JSON array of issue snapshots or an object with an `issues`
array. Issue bodies and unrelated fields are discarded before classification.

## Fetch open issues from GitHub

```bash
export GITHUB_TOKEN=...
python scripts/issue_roadmap_controller.py --fetch-github --repo CarAutopsy/carautopsy > /tmp/issue-roadmap-proposals.json
```

A token is optional for public repositories, but authenticated requests have
higher API rate limits. The controller uses the GitHub issues read endpoint,
follows only validated `api.github.com` pagination links, enforces a page cap,
and continues through its fixed repository endpoint. It retains only number,
title, state, label names, URL, and a boolean pull-request marker. Nested label
metadata, the pull-request API object, issue bodies, and unrelated fields are
discarded.

## Safety and scope

- The CLI writes only to standard output; it has no file-output option.
- No issue labels, comments, roadmap files, workflow files, or task queues are
  written by the controller.
- Every actionable proposal requires explicit owner approval.
- Any present `pull_request` marker is excluded, including malformed or falsy
  marker values; an absent marker is treated as an issue.
- Ambiguous and conflicting snapshots remain visible as owner-triage records.
- Classification counts retain informational, blocked, and duplicate issue
  snapshots in the report without creating roadmap proposals for them.
- No task dispatch, automatic merge, provider call, Hive retrieval, source
  manifest update, or readiness activation is performed.
- Roadmap-state reconciliation, stale-state detection, dependency resolution,
  cycle detection, and an owner-gated apply path remain future integration work.
  This CLI is a proposal-only first controller slice, not completion of issue
  #86.

## Reconciliation dry-run with a local evidence fixture

The proposal-only reconciliation core can also be exercised against a local
fixture:

```bash
python scripts/issue_roadmap_controller.py --reconcile-input tests/fixtures/roadmap-reconciliation.example.json
```

The fixture contains `roadmap_tasks`, `issue_snapshots`,
`pull_request_evidence`, and `check_runs`, with the owner-approval list deliberately excluded from fixture control. The CLI projects each record to a fixed metadata
allowlist and discards issue bodies, PR bodies, check output, and unrelated
fields. Fixtures cannot self-approve tasks or weaken the required `audit` and
`validate` checks; all status changes remain pending owner approval. The reconciliation core validates dependencies/cycles, stale source
timestamps, cross-reference markers, exact PR-head checks, and owner approval.

This mode is an offline test harness: it does not fetch or authenticate the
GitHub evidence in the fixture. A live collector must obtain issue/PR
cross-reference events, PR metadata, and check-runs from the GitHub API before
passing projected records to the pure reconciler. The report is printed to
stdout and never applies changes.
