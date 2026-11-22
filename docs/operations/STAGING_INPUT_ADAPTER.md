# Staging input adapter

**Status:** read-only adapter for PR #156. It lets the identity/conflict tool
analyze the real 48-record staging batch without changing any staging file.

## CLI

```bash
python scripts/staging_input_adapter.py \
  --input-dir docs/research/staging-snapshot-2026-11-22 \
  --report docs/research/staging-adapter-output.json \
  --tool-input docs/research/staging-adapted-tool-input.json
```

`--check` validates without writing. `--expected-count` defaults to 48 and can
be overridden only for synthetic tests. Exit codes: `0` success, `3` validation
or unsafe-path error. Report paths under `catalog/`, `catalog/variants/` and
`staging/` are refused.

## Mapping rules

- `variant_id` = JSON filename stem with `.json` removed; no case or whitespace
  changes. This is stable and deterministic across reruns.
- `identity.make` ← `brand`; `identity.model` ← `model`;
  `identity.variant` and `identity.trim` ← `variant` (null if absent);
  `model_year`, `body_style`, `powertrain`, `drivetrain` ← same-named fields.
- `specifications.battery_capacity_kwh` ← `battery_capacity_usable_kwh`;
  `specifications.range` ← `wltp_range_km`. Gross battery capacity remains only
  in the preserved raw record; it is not substituted.
- `price` ← `price_tier`, `price_value`, `price_source_url`, `price_source_date`,
  `vat_basis`, `price_confidence`; all unspecified values stay null.
- `provenance.sources` ← `source_id`, `source_url`, `source_date` when any exist.

No value is inferred, normalized into existence, merged or promoted. The
complete original record is preserved under `raw` in the adapter output.

## Validation

The adapter rejects a batch unless it contains exactly 48 records (default),
derived IDs are unique, `brand` and `model` are present, and raw values are
preserved exactly. Output is sorted, key-stable and timestamp-free.

## Boundary

The adapter writes only documentation artifacts under `docs/research` or
`docs/operations`. It never writes catalog or staging records, calls a provider,
uses a secret, or changes a gate.
