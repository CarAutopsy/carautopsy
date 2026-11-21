# STEP 2 — attributed EEA adapters: results and blocker

**Status:** Adapters implemented and proven fail-closed; **no gate-ready WLTP-era variant was produced** because a real 2018–2026 variant-level sample is not publicly range-readable. No catalog file was written.

## Delivered
- `scripts/validate_eea_with_adapters.py` — WLTP-year filter, CO2→L/100km derivation with `derived: true` / `derived_from: co2_nedc_wltp` / formula, attributed price attachment or `price_pending: true`, gate execution, coverage report and proposal artifacts.
- `tests/test_validate_eea_with_adapters.py` — 8 offline tests.
- `docs/data-sources/sample/eea_at_120.tsv` — 120 real Austrian records from the EEA public share (byte-range sampled).
- `docs/data-sources/proposals/*.json` — 120 proposal artifacts, all `status: rejected`.

## Run (exact)
`python scripts/validate_eea_with_adapters.py --sample docs/data-sources/sample/eea_at_120.tsv --dataset-year 2017 --no-taxes`

```
sampled: 120 passed: 0 rejected: 120
proposal artifacts: 120 -> docs/data-sources/proposals
coverage %: all nine gate fields 100.0
rejection reasons: 120x NEDC-only file, WLTP required
catalog/variants written: 0
```

## Why 0 passed
The only publicly range-readable EEA microdata file is the 2017 plain UTF-16LE TSV. It is NEDC-only and 2017 is outside the owner-approved 2018–2026 window, so every record is rejected by the new filter. This is the intended fail-closed behaviour, not a mapping failure: with the file-level filter disabled, field coverage is 100% on all nine gate fields, including derived consumption and price-or-pending.

2018 and 2019 EEA shares contain only Deflate64 ZIP archives (2018: `CO2_passenger_cars_v18_csv.zip`, 196,810,414 bytes; 2019 share has metadata only). Python's `zipfile` cannot decompress method 9 and no local 7z/libarchive path is available, so a genuine WLTP-era 100–200 record sample cannot be obtained without a decision to download and extract a full annual archive.

No WLTP value, price or consumption was fabricated. The CO2 divisor is applied only to values present in the source and is always labelled derived, never measured.

## Owner decision needed before STEP 3
1. Approve downloading the 196 MB 2018 annual ZIP (or provide a range-readable WLTP-era export) to obtain a genuine 100–200 record WLTP sample.
2. Approve an attributed Austrian price source, or confirm that `price_pending` records stay out of the catalog until prices arrive.
3. Decide supported statutory years: the current AT tax pack covers 2025–2029, while the public microdata available here is 2017–2019.

## STEP 3 instructions (after those decisions)
1. Re-run the validator with a genuine WLTP-era sample and `--dataset-year 2018..2026`.
2. Require 100% coverage and a non-zero gate-pass count before any proposal is promoted.
3. Owner reviews the proposal artifacts; only then copy approved files into `catalog/variants/` in a separate PR with exact-head CI.
4. Never promote `price_pending` or derived-only records without explicit owner acceptance.
