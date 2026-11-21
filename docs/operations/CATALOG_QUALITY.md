# Offline vehicle catalog quality milestone

Status: **OFFLINE VALIDATION ONLY. NO LIVE RETRIEVAL.**
Last reviewed: 2026-11-21

`scripts/catalog_quality.py` extends the existing catalog validation chain with
quality evidence. It calls `scripts.validate_catalog.validate_catalog` for the
structural JSON-schema contract; it does not replace that validator or the
vehicle schema. [STATIC_READ]

## What it adds

- **Canonical normalization** — make/model/generation/variant slugs and a
  stable identity key from `make | model | generation | variant | model_year`.
- **Duplicate and conflict detection** — duplicate `variant_id`, duplicate
  identity keys, and conflicting values for watched specification fields.
- **Evidence provenance and confidence** — tier scoring from source entries
  (`official`, `high`, `medium`, `low`, `unknown`) with independent-source counts
  and reviewed-by state.
- **Missing-data and completeness metrics** — per-section and overall populated
  field ratios, critical missing fields, and complete-variant counts. Unknown
  values remain `null`; the tool never treats null as zero.
- **Freshness and stale detection** — per-source `retrieved` age against a
  configurable threshold (default 365 days), with `STALE_SOURCE`,
  `UNVERIFIED_PROVENANCE`, `INVALID_PROVENANCE_TIMESTAMP` and
  `FUTURE_PROVENANCE` findings.
- **Incremental refresh planning** — deterministic P1/P2 plan entries with
  reasons. `refresh_enabled` and `network_permitted` are always false; the tool
  only proposes owner-reviewed research. [STATIC_READ]

## Machine-readable output

Run: `python scripts/catalog_quality.py --report reports/catalog-quality.json
--now 2026-11-25T12:00:00Z`. The report contains `catalog_sha256`,
`report_sha256`, gates, structural error count, blocking finding count,
completeness ratios, confidence counts, per-variant evidence, findings and the
refresh plan. `report_sha256` excludes `generated_at` so identical catalog state
yields the same digest at different evaluation times. [STATIC_READ]

CI runs the tool in `.github/workflows/validate-catalog.yml` and uploads the
report as an artifact. [STATIC_READ]

## Measured baseline

Measured on `main` HEAD `4e4398fe4632e071964f3b094073573df5313c4b` with
`--now 2026-11-25T12:00:00Z`: [TRACE_EXECUTION]

| Metric | Baseline |
|---|---:|
| Variants | 6 |
| Structural errors | 0 |
| Blocking findings | 0 |
| Overall completeness | 0.3277 |
| Complete variants | 0 |
| Refresh-plan entries | 6 |

The committed clean fixture `tests/fixtures/catalog_quality/clean.json` reaches
completeness 1.0 with zero blocking findings; the regression suite also proves
lower completeness, P1 refresh priority, stale-source detection, duplicate and
conflict detection, and unchanged paused gates. These are tool-quality
measurements, not a claim that any real vehicle specification is verified.
[TEST_OBSERVED]

## Safety

`HIVE_RESEARCH_PAUSED` remains active and `VERIFIED_RETRIEVAL_AVAILABLE`
remains `False`. The tool opens no socket, reads no secret, makes no provider or
paid call, does not mutate `catalog/`, and does not create issues or PRs.
Owner activation rules in `docs/operations/SOURCE_ACTIVATION.md` are unchanged.
[OWNER_DECISION]
