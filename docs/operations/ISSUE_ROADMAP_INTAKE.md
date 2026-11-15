# GitHub issue roadmap intake — dry-run controller

The issue intake controller is deliberately read-only. It consumes GitHub issue
metadata or a local JSON fixture, applies the pure classifier in
`scripts/issue_roadmap.py`, and emits a deterministic JSON proposal artifact.

## Run with the example fixture

```bash
python scripts/issue_roadmap_controller.py --input tests/fixtures/issue-intake.example.json
```

A fixture may be a JSON array of issue snapshots or an object with an `issues`
array. The issue body is ignored by the classifier.

## Fetch open issues from GitHub

```bash
export GITHUB_TOKEN=...
python scripts/issue_roadmap_controller.py --fetch-github --repo CarAutopsy/carautopsy --output /tmp/issue-roadmap-proposals.json
```

A token is optional for public repositories, but authenticated requests have
higher API rate limits. The controller uses the GitHub issues read endpoint,
paginates with bounded page size, and retains only number, title, state, labels,
URL, and the pull-request marker.

## Safety and scope

- No issue labels, comments, roadmap files, workflow files, or task queues are
  written.
- Every actionable proposal requires explicit owner approval.
- Ambiguous and conflicting snapshots remain visible as owner-triage records.
- Issue bodies and other unneeded API fields are discarded before proposal
  generation.
- No task dispatch, automatic merge, provider call, Hive retrieval, source
  manifest update, or readiness activation is performed.
- Roadmap-state reconciliation, stale-state detection, dependency resolution,
  cycle detection, and an owner-gated apply path remain future integration work.
  This CLI is a proposal-only first controller slice, not completion of issue
  #86.
