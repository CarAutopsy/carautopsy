# GitHub issue roadmap intake — dry-run controller

The issue intake controller is deliberately read-only. It consumes GitHub issue
metadata or a local JSON fixture, applies the pure classifier in
`scripts/issue_roadmap.py`, and emits a deterministic JSON proposal artifact
to standard output.

## Run with the example fixture

```bash
python scripts/issue_roadmap_controller.py --input tests/fixtures/issue-intake.example.json
```

To save a report outside the repository, redirect standard output:

```bash
python scripts/issue_roadmap_controller.py --input tests/fixtures/issue-intake.example.json > /tmp/issue-roadmap-proposals.json
```

A fixture may be a JSON array of issue snapshots or an object with an `issues`
array. The issue body is ignored by the classifier.

## Fetch open issues from GitHub

```bash
export GITHUB_TOKEN=...
python scripts/issue_roadmap_controller.py --fetch-github --repo CarAutopsy/carautopsy > /tmp/issue-roadmap-proposals.json
```

A token is optional for public repositories, but authenticated requests have
higher API rate limits. The controller uses the GitHub issues read endpoint,
paginates with bounded page size, and retains only number, title, state, labels,
URL, and a boolean pull-request marker. Nested label metadata, the pull-request
API object, issue bodies, and other unrelated fields are discarded.

## Safety and scope

- The CLI writes only to standard output; it has no file-output option.
- No issue labels, comments, roadmap files, workflow files, or task queues are
  written by the controller.
- Every actionable proposal requires explicit owner approval.
- Ambiguous and conflicting snapshots remain visible as owner-triage records.
- No task dispatch, automatic merge, provider call, Hive retrieval, source
  manifest update, or readiness activation is performed.
- Roadmap-state reconciliation, stale-state detection, dependency resolution,
  cycle detection, and an owner-gated apply path remain future integration work.
  This CLI is a proposal-only first controller slice, not completion of issue
  #86.
