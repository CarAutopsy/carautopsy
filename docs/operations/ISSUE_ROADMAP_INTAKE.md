# GitHub issue roadmap intake and reconciliation

The issue intake controller is read-only. It supports two separate dry-run
modes: issue classification and roadmap status reconciliation. Both emit
deterministic JSON to standard output and never write repository or GitHub
state.

## Classify issues

Run with the example fixture:

```bash
python scripts/issue_roadmap_controller.py --input tests/fixtures/issue-intake.example.json
```

Fetch open issue metadata from GitHub:

```bash
export GITHUB_TOKEN=...
python scripts/issue_roadmap_controller.py --fetch-github --repo CarAutopsy/carautopsy
```

A token is optional for public repositories, but authenticated requests have
higher API rate limits. The controller uses the fixed GitHub issues endpoint,
follows only validated `api.github.com` pagination links, enforces a page cap,
and retains only number, title, state, labels, URL, and a boolean pull-request
marker. Issue bodies and unrelated API fields are discarded before
classification.

## Reconcile roadmap status from a fixture

Run the proposal-only reconciliation mode:

```bash
python scripts/issue_roadmap_controller.py --reconcile-input tests/fixtures/roadmap-reconciliation.example.json
```

The fixture contains `roadmap_tasks`, `issue_snapshots`,
`pull_request_evidence`, and `check_runs`. The CLI projects each record to a
fixed metadata allowlist and discards issue bodies, PR bodies, check output,
and unrelated fields.

**The fixture cannot self-approve tasks or weaken required CI checks.** The CLI
always leaves status changes pending owner approval and always requires the
`audit` and `validate` check-runs on the exact PR head SHA. The pure
reconciliation function accepts an explicit owner-approved task-key set for
future trusted callers, but this fixture CLI never supplies one.

The reconciliation core validates stable task identities, dependencies and
cycles, stale issue timestamps, GitHub cross-reference markers, merged PR
metadata, and exact-head CI evidence. A closed issue alone or an opened PR
alone never marks a task done. The report is deterministic and printed only
to stdout.

This mode is an offline test harness: it does not fetch or authenticate the
GitHub evidence in the fixture. A live collector must obtain issue/PR
cross-reference events, PR metadata, and check-runs from the GitHub API before
passing projected records to the pure reconciler.

## Safety and scope

- No issue labels, comments, roadmap files, workflow files, or task queues are
  written by either CLI mode.
- Every actionable issue proposal and every reconciliation status change
  remains owner-gated.
- Any present `pull_request` marker is excluded, including malformed or falsy
  marker values; an absent marker is treated as an issue.
- Ambiguous and conflicting snapshots remain visible as owner-triage records.
- Classification counts retain informational, blocked, and duplicate issue
  snapshots in the report without creating roadmap proposals for them.
- Reconciliation preserves current status when evidence is missing, stale,
  mismatched, duplicated, or dependency-blocked.
- No automatic merge, task dispatch, provider call, Hive retrieval, source
  manifest update, OEM access, or readiness activation is performed.
- No second scheduler is introduced; the existing 15-minute pipeline is
  unchanged.


## Render a deterministic proposal comment (stdout only)

To render a reconciliation report as a stable Markdown proposal comment:

```bash
python scripts/issue_roadmap_controller.py --reconcile-input tests/fixtures/roadmap-reconciliation.example.json --render-proposal
```

The renderer validates proposal-only/no-write flags, owner approval, unique
task identities, exact PR-head evidence, and the merge commit SHA for any
`done` proposal. It sorts entries and computes a content-derived SHA-256
proposal ID, so identical reports produce byte-identical Markdown and IDs.
Pending-approval entries include the supporting issue number, linked PR, exact head SHA, merge SHA when applicable, and repository-bound links to exact successful check-run IDs. The renderer rejects cross-repository, mismatched-ID, duplicate, or Markdown-injecting check URLs. Roadmaps may contain up to 5,000 entries; when detailed Markdown would exceed the safe comment limit, the comment becomes a compact count-and-artifact-ID summary while the deterministic JSON retains every task and evidence record. The fixed comment marker is groundwork for a future idempotent publisher. This command only prints to stdout; it never calls the GitHub comments API.

Issue #86 remains open. Live GitHub evidence collection, idempotent proposal
publishing, a separately owner-authorized apply path, and workflow wiring
remain future integration work.
