# Offline bulk catalog ingestion

`scripts/ingest_bulk_catalog.py` turns the committed EEA bulk-source evidence into
catalog-shaped staging records. It is **offline, read-only with respect to the live
catalog, and fail-closed**. It never downloads data, never calls a provider, never
reads secrets, and never writes to `catalog/variants/`.

## Hard prerequisites (checked at startup)

1. `docs/data-sources/bulk-source-selection.md` must exist and identify
   **EEA type-approval CO2 microdata** with licence **CC BY 4.0**. If it is
   missing or does not name a permitted source, the command exits with code 3.
2. `--source` must point to a JSON config inside the repository. The committed
   config is `docs/data-sources/bulk-sources/eea-at-2018.json`.
3. Every path referenced by the config (sample TSV, identity map, price
   evidence, statutory rules) must exist inside the repository.
4. `--output-dir` must be a branch-scoped path under `staging/`. A path in
   `catalog/variants/` is rejected with code 4.

## Usage

```bash
# Dry-run: at most 200 records, no staging files written
python scripts/ingest_bulk_catalog.py \
  --source docs/data-sources/bulk-sources/eea-at-2018.json \
  --dry-run --limit 200 --report /tmp/ingest-dry.json

# Batch: write at most --batch-size records to a staging directory
python scripts/ingest_bulk_catalog.py \
  --source docs/data-sources/bulk-sources/eea-at-2018.json \
  --limit 500 --batch-size 100 \
  --output-dir staging/catalog-batch-001 \
  --report /tmp/ingest-report.json
```

### CLI arguments

| Argument | Meaning |
|---|---|
| `--source` | Committed bulk source config JSON (required) |
| `--limit` | Maximum source rows to read (default 200) |
| `--dry-run` | Process at most 200 rows; write no staging files |
| `--batch-size` | Maximum records written per invocation (default 50) |
| `--output-dir` | Branch-scoped staging directory; required unless `--dry-run` |
| `--report` | Machine-readable JSON report path (required) |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (report emitted) |
| 2 | Bad arguments or invalid source config |
| 3 | Source-selection gate failed (missing/invalid document) |
| 4 | Unsafe output path (catalog or non-staging directory) |
| 5 | Read/map/statutory error |

## Inputs (all already committed)

- Sample: `docs/data-sources/sample/eea_at_2018_wltp_sample.tsv` (EEA, CC BY 4.0)
- Identity evidence: `docs/data-sources/identity-map/v1.json`
- Price evidence: `docs/data-sources/price-evidence/v1.json`
- Statutory rules: `docs/data-sources/statutory/at-rules-v1.json`
- Schema: `schemas/vehicle-variant.schema.json` (used unchanged)

## Pipeline

1. **Read** — parse the EEA TSV through the existing `read_rows`/`map_row`
   adapters. Only `MS == "AT"` rows are accepted.
2. **Resolve** — look up the exact six-field key
   `make | model | variant | powertrain | model_year | market` in the identity
   and price evidence. The identity hook resolves make, model, trim, model
   year, body style and powertrain from evidence and source facts only;
   undocumented optional fields stay null.
3. **Gate** — require verified in-period statutory rules and zero readiness
   findings; validate each record against the unchanged catalog JSON schema.
4. **Detect duplicates/conflicts** — use `catalog_quality.normalize_identity`
   and `detect_duplicates` across both the staged batch and the existing live
   catalog (read-only). The first record per identity key is kept; later
   members and conflicting records are dropped and counted.
5. **Write** — in batch mode, write at most `--batch-size` records into the
   staging directory. Every record carries `catalog_written: false`.

## Outputs

- **Staging records** (batch mode only): `<output-dir>/<variant_id>.json`, in the
  existing catalog schema plus explicit `resolved_identity`,
  `price_verification`, `statutory`, `ingestion`, `tco_ready` and
  `catalog_eligible` blocks.
- **Report** (always): counts for `read`, `mapped`, `rejected`, `duplicates`,
  `conflicts` and `written`; per-record rejection reasons; duplicate and
  conflict findings; source provenance (URL, licence, extraction date); and
  `catalog_variants_written: 0`.

## Safeguards and limitations

- No network access anywhere in the script or its tests.
- No secrets, API keys, paid providers, or live retrieval.
- No write to `catalog/variants/`; no change to workflow, CI or approval gates.
- No invented prices, specifications, VINs or identity fields. Rows lacking
  identity or price evidence are rejected with explicit reasons.
- The source-selection doc itself notes that EEA microdata has no price; all
  prices come from the separate curated price-evidence file.
- Kodiaq/Karoq remain unresolved (`no_source_found_after_exhaustive_search`);
  see `kodiaq-karoq-search-report.md` on the research branch. They are not
  ingested.
- Staging output is **not** the catalog. A separate owner-approved batch PR is
  required before any record enters `catalog/variants/`.

## Typical results

The committed 2018 sample contains 154 Austrian rows. With the current
evidence, 114 are identity+price resolved; the remaining 40 lack a verified
price. Because the existing catalog already contains those 114 records from
batches 001/002, a repeat ingestion reports them as duplicates and writes zero
new records — which is the intended idempotence behaviour.
