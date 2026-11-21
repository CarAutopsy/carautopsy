# STEP 3 — owner-review checkpoint (no catalog write)

**Status:** Awaiting owner approval. No PR opened, no `catalog/variants/` write, no gate change, no activation.

## Data access
- Downloaded the full 196,810,414-byte 2018 EEA ZIP from public share `https://sdi.eea.europa.eu/data/b319cb95-2c93-4635-8177-e5e0e4f48c1b` into a local temp directory; not committed.
- Extracted with `zipfile-deflate64` 0.2.0 (no 7z/p7zip available). Inner CSV is UTF-8 TSV, 2,923,316,145 bytes uncompressed.
- Real sample: **154 Austrian rows with genuine `Ewltp` (WLTP) CO2** — 85 Diesel, 60 Petrol, 9 Electric. Sample committed at `docs/data-sources/sample/eea_at_2018_wltp_sample.tsv`.

## Run and results
`python scripts/validate_eea_with_adapters.py --sample docs/data-sources/sample/eea_at_2018_wltp_sample.tsv --dataset-year 2018 --no-taxes`

```
sampled: 154 passed: 9 rejected: 145
proposal artifacts: 9 -> docs/data-sources/proposals
coverage %:
  identity.make/model/powertrain/vehicle_class: 100.0
  registration.first_registration_date: 100.0
  dimensions.max_permissible_mass_kg: 100.0
  offers.price_or_pending: 100.0
  performance.combustion_engine_power_w: 94.2
  extensions.fuel_consumption_l_100km.real_world: 94.2
rejection reasons: 145x offers[0].purchase_price_excl_vat_eur must be a finite positive number
catalog/variants written: 0
```

The 9 passes are all Nissan A02 BEVs (same vehicle repeated with different type-approval IDs) — deduplicate before any catalog write. Price is `null` + `price_pending: true` because no reliable bulk Austrian MSRP source was available; no price was fabricated. The WLTP-year filter remains strict.

## Blockers to statutory acceptance
With taxes enabled the gate is 0/154: missing 2018 NoVA rules, 2018 ICE motor-tax rules and BEV schedule. Owner decision 3 approved extending the AT pack to 2017–2019, but no statutory rates were added: BMF publishes historical tables and the values must be verified, not reconstructed from memory. The 9 passes are structural (`--no-taxes`) only.

## Owner decisions needed before STEP 4
1. Which (if any) of the 9 near-duplicate BEV proposals to keep (recommend one after deduplication).
2. Provide/approve verified 2017–2019 NoVA and motor-tax rate tables for the AT pack.
3. Approve an attributed Austrian price source, or confirm `price_pending` records stay out of the catalog.

## STEP 4 (after approval)
Create `feat/catalog-batch-001` from current `main`, copy only approved proposal JSONs into `catalog/variants/`, run exact-head Validate Catalog + Repository Audit, open a PR with the approved list and rationale. No merge, no direct push to main.
