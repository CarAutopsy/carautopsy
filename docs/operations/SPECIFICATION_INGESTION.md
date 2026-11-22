# Offline specification ingestion

**Status:** tool implementation (PR #153). Offline and owner-controlled. It does
not write catalog or staging records, call a provider, or change any gate.

## CLI

```bash
# validate only
python scripts/spec_ingestion.py --check --input tests/fixtures/spec_ingestion/complete.json

# emit a deterministic report under docs/research or docs/operations
python scripts/spec_ingestion.py \
  --input tests/fixtures/spec_ingestion/complete.json \
  --report docs/research/spec-ingestion-report.json
```

Exit codes: `0` success/check, `2` CLI error, `3` validation or unsafe-path error.
Report paths under `catalog/`, `catalog/variants/` and `staging/` are refused.

## Canonical record

`schemas/vehicle-specification.schema.json` defines the canonical format:

- `variant_id`
- `identity`: make, model, variant, model_year, body_style, powertrain,
  fuel_type, drivetrain, transmission, model_specific_id
- `specifications`: battery_capacity_kwh, electric_range_km, dimensions
  (length_mm, width_mm, height_mm), weight_kg, seats
- `provenance`: source_id, source_url, retrieval_date, source_type,
  license_attribution_status, confidence, limitation
- `evidence_status`: `complete`, `partial`, `conflicting` or `invalid`

Identity values are copied exactly; the detection-only identity key is
case-insensitive but never rewrites stored values. Missing evidence stays
`null` — no value is inferred, normalized into existence, or merged.

## Validation

The pipeline rejects observations with:

- missing mandatory identity fields (`make`, `model`, `variant`, `model_year`);
- invalid ISO `retrieval_date` or out-of-range `model_year`;
- invalid units or out-of-bounds numeric fields;
- unsupported enum values (powertrain, fuel type, drivetrain, body style,
  transmission, confidence, source type, licence status);
- unsupported provenance (missing source id, non-http(s) URL, missing date,
  unknown source type or licence status).

Within a batch, duplicate identities and conflicting spec evidence are reported
as findings. Conflicting records remain separate and are marked `conflicting`.

## Idempotence and determinism

Output is sorted, key-stable, free of timestamps, and includes a SHA-256 digest
of the input file. Rerunning on unchanged input produces byte-identical output.

## Owner-review boundary

This tool prepares canonical specification records and findings only. It never
assigns a price, activates a provider, writes catalog or staging records, or
promotes an approximate value to verified. Owner review is required before any
record enters a staging batch or catalog PR.
