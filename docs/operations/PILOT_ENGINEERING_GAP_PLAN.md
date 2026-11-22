# Pilot engineering gap plan

**Status:** implementation review and remaining-work register. No gate is enabled
and no catalog or staging write is authorized here.

## 1. Implemented interfaces

### Staging runner

```bash
python scripts/pilot_staging_runner.py \
  --candidates docs/research/pilot-gap-price-candidates.json \
  --output-dir staging/pilot-batch-001-002 \
  --report /tmp/pilot-staging-report.json

python scripts/pilot_staging_runner.py \
  --candidates docs/research/pilot-gap-price-candidates.json --dry-run
```

Arguments: `--candidates` (required), `--output-dir` (required unless dry-run),
`--report` (optional; when supplied with `--dry-run`, the report file is still
written), `--dry-run` (writes no staging records; it does not suppress a
requested report file).
Exit codes: `0` success or dry-run, `3` unsafe output/report path, `4` batch
rejected by validation.

Dry-run report keys: `schema_version`, `status`, `source_candidate_file`,
`dry_run`, `output_dir`, `accepted`, `rejected`, `duplicates`, `conflicts`,
`errors`, `written`, `written_files`, `catalog_variants_written`,
`provider_calls`, `rejection_details`, `duplicate_candidates`,
`conflict_candidates`. The CLI prints all keys except `written_files` and
`rejection_details`.

### Staging record format

A staged record is the original candidate plus canonicalized fields
`price_value`, `price_source_url`, `price_source_date`, `price_confidence`,
`price_adjustment_method`, `vat_basis`, `review_required`, and the safety fields
`catalog_written: false`, `staging_only: true`, `staging_report_source`,
`provider_calls: 0`, `staged_at`.

### Coverage scoreboard

```bash
python scripts/coverage_scoreboard.py \
  --candidates docs/research/pilot-gap-price-candidates.json \
  --weights docs/research/registration-weights-v1.json \
  --report /tmp/coverage-report.json
```

Report keys include `total_models`, `models_by_price_tier`, per-tier counts,
`registration_weighted_coverage`, `price_quality_coverage`,
`correction_queue_count`, `tco_ready_count`, `coverage_gaps`, and SHA-256 digests
of the candidate and weight inputs. Weights are a provisional priority proxy.

### One Auto adapter

```bash
python scripts/oneauto_adapter.py --probe
```

Library entry points: `connectivity_probe()` and `fetch_enrichment()` accept
injected transport/clock/sleeper for deterministic tests.

## 2. Remaining engineering work

- **Catalog-conflict detection.** The runner currently detects duplicates and
  conflicts only within the candidate batch, and its deduplication key includes
  the source URL. Two records for the same vehicle with different source URLs and
  different prices are therefore not currently reported as a conflict. Add
  identity-level within-batch price comparison plus a read-only comparison of
  each staged identity against `catalog/variants/`, with explicit conflict counts
  and a hard stop on collisions. These are prerequisites for gates 4 and 7 of the
  staging plan.
- **Per-run report persistence.** Decide whether the staging report is an
  external artifact or a committed documentation artifact; the runner supports
  `--report` but does not choose a repository location.
- **Optional owner-limited batch selection.** Add an explicit filter (for
  example `--tiers approximate`) so the owner can stage only the 12 approximate
  candidates without editing the candidate file.
- **Exact final-SHA validation.** Re-run compileall, the full test suite,
  catalog validation and coverage generation on the exact head used for any
  later approval.

## 3. Catalog-conflict detection rules (to implement)

- Normalize identity as `make | model | variant | model_year` using the existing
  `catalog_quality.normalize_identity` conventions.
- Treat an exact `variant_id` match or an identical normalized identity key as a
  conflict with the live catalog; report it and block the batch.
- Treat differing price values for the same normalized key within the batch as a
  conflict; never keep the "winner" silently.
- Never read a catalog record to overwrite it; the catalog is read-only for the
  runner.

## 4. Provenance retention rules

- Preserve `source_id`, source URL, source date, currency, VAT basis, confidence,
  adjustment method, retrieval date and `review_required` verbatim.
- Do not persist provider headers, raw response bodies, tokens, cookies or
  key-like values.
- Redact key-like strings from every report and exception path.
- Hash retained response payloads rather than storing them.

## 5. Approximate-price review workflow

1. Research candidate is committed with a dated, attributable Austrian source.
2. Price-tier validator confirms `approximate` and complete provenance.
3. Owner reviews source URL, date, VAT basis and model-level limitation.
4. Staging record retains `review_required: true`.
5. Provisional TCO output displays the tier and uncertainty notice.
6. A verified correction requires a new source and an owner-approved change
   reason; the promotion guard blocks automated upgrades.

## 6. Coverage-scoreboard integration

- Generate the scoreboard from the same committed candidate file used by the
  staging runner so counts reconcile.
- Report the candidate and weight digests plus the exact commit SHA.
- Keep approximate, cross-market, range and unavailable records visible in the
  correction queue; never count them as verified.
- Replace the provisional weight file with owner-approved registration data
  before treating the weighted figure as an acceptance metric.

## 7. One Auto API adapter limitations

- Classified `enrichment_only` / `cross_check_only`; Austrian price coverage is
  unverified, so its output can never be `verified` Austrian pricing.
- Reads the secret only from the environment abstraction; never stores or prints
  the value.
- Probe performs at most one bounded request; enrichment uses rate limiting,
  exponential backoff and field whitelisting.
- Default endpoint constants are unverified and must be confirmed by the owner
  before any authorized live call.
- No live API call is made in tests, CI or this planning task.

## 8. Required tests

Already implemented: tier validation, promotion guard, VAT/provenance validation,
zero-placeholder rejection, redaction, missing-secret handling, rate limiting,
backoff, HTTP error classification, malformed responses, staging dry-run,
staging validation failure, and coverage calculations.

Still required: catalog-conflict detection tests, batch-selection filter tests,
CLI exit-code tests, exact-final-SHA validation workflow checks, and a test that
the live transport is never invoked without explicit owner authorization.

## 9. Documentation updates

Keep `docs/operations/PILOT_PRICE_TIER_WORKFLOW.md`, the staging batch plan, the
evidence gap plan and this document synchronized with any interface change.
Record exact commands, exit codes, report keys and owner decisions.

## 10. Owner approvals

- Approve the first real staging batch scope (all 48 or 12 approximate only).
- Approve catalog-conflict detection before relying on gate 7.
- Approve any live One Auto or EV Database research pass and exact endpoints.
- Approve any catalog PR separately; no catalog ingestion is authorized here.
