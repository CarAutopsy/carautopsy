# Austria Vehicle Data & TCO Audit — 2026-11-10

**Scope:** Read-only audit of `main` at `959d35179cbf9e4f3c02c9c8723d96b59f3419c5`.
**Status:** Initial findings; no statutory values or vehicle specifications changed.

## Executive summary

The provider smoke test and full workflow may pass while the resulting vehicle data and TCO figures remain incomplete or misleading. The audit found validation, catalog completeness, configuration-contract, and tax-test gaps. Treat current TCO output as provisional until the blocking findings below are addressed.

## Findings

### F-001 — Catalog validator does not validate catalog records
**Severity: Critical**

File: `scripts/validate_catalog.py`

The script imports (or installs) `jsonschema` and prints `Validation script ready.`; it does not load a schema, enumerate `catalog/variants/*.json`, or validate any record. The referenced `schemas/vehicle.schema.json` path is absent from the repository.

**Impact:** CI or a manual run of this script can report readiness without checking required fields, types, units, nullability, provenance, or variant identity. Incomplete records can pass unnoticed.

**Required remediation:** Add a versioned vehicle schema and make the validator enumerate all catalog JSON files, validate each record, report file/field-specific errors, and exit non-zero on any failure. Add tests proving invalid and valid fixtures produce the expected exit status.

### F-002 — Catalog contains placeholder records, not usable vehicle variants
**Severity: Critical**

At the audited revision, `catalog/variants/` contains six records. Four contain only schema version, variant ID, status, make, and low-confidence provenance:
- `fiat.500e.hatch.42kwh.json`
- `kia.ev3.my25.long-range-rwd.json`
- `renault.5.etech.52kwh-150.json`
- `tesla.model-y.juniper.rwd-60.json`

The remaining Tesla Model 3 record contains detailed fields but its only source is explicitly an EV Database listing marked `reference-only` / `field_inventory`, while the catalog protocol says EV Database is a field checklist only. The VW Tiguan record labels its price as a placeholder and its source as manual-curation placeholder.

**Impact:** The catalog's record count overstates its usable, sourced coverage. Downstream comparisons may omit records or calculate from unsupported values.

**Required remediation:** Track completeness separately from record count. Do not publish placeholder values as verified specifications or prices. Populate fields only from permitted official sources and retain field-level provenance; otherwise keep the field unknown and label the variant incomplete.

### F-003 — TCO engine reads configuration keys that do not exist in the Austria defaults
**Severity: Critical**

Files: `scripts/autonomous_pipeline.py`, `country-packs/AT/defaults.yaml`

The engine expects:
- `horizon_years_default` and `annual_km_default`; neither exists in the defaults file, so hidden code fallbacks are used.
- `energy.electricity_tariff_eur_kwh`; the file defines `electricity.default_tariff_eur_kwh`. BEV energy cost therefore falls back to 0.
- `tyres.interval_km` and `tyres.set_cost_eur`; the file defines `tyres.replacement_interval_km` and `tyres.average_cost_eur`.
- `inspection_annual_proxy_eur`; the file has no such key, so the engine silently uses a hard-coded fallback.
- `insurance_proxy_annual_eur`; the file defines `insurance_proxy.bev_annual_eur` and `insurance_proxy.ice_annual_eur`.
- `maintenance.*` values are present in YAML but the engine instead uses hard-coded `MAINT` constants.

**Impact:** BEV energy cost is currently zero under the checked-in defaults; multiple other TCO inputs are ignored or silently replaced by hard-coded values. This makes comparisons unreliable and makes configuration changes ineffective.

**Required remediation:** Define one documented configuration contract and use it consistently. Reject missing required assumptions instead of silently defaulting to zero. Add deterministic tests for BEV and ICE cost components, including assertions that changing each YAML assumption changes the calculated result.

### F-004 — Motorbezogene Versicherungssteuer configuration is not consumed
**Severity: High**

File: `scripts/autonomous_pipeline.py`

The engine reads `formula.power.rate_eur_per_kw_over_threshold` and `formula.co2.rate_eur_per_gkm_over_threshold`, but the checked-in Austria tax pack uses `rate_eur_per_kw_over_threshold` and `rate_eur_per_gkm_over_threshold` under those sections. More importantly, the code expects `motorbezogene_versicherungssteuer.exemptions` and formula keys, but this has no test coverage. The cost function returns a monthly value from the formula and TCO multiplies it by 12 and the horizon.

**Impact:** There is no regression guard against configuration drift, incorrect units, or incorrect annualization. Statutory outputs cannot be considered verified based on the workflow's success.

**Required remediation:** Add tests against authoritative, dated Austrian examples and assert both monthly and horizon totals. Verify the current legal formula before changing any values.

### F-005 — Austria tax pack has no executable regression tests and its effective-date metadata is inconsistent
**Severity: High**

Files: `country-packs/AT/taxes.yaml`, `country-packs/AT/manifest.yaml`, `country-packs/AT/tests/`

The manifest marks the country pack `verified`, while `taxes.yaml` labels itself `verified-draft`. The manifest and tax comments cite different effective dates (2024-01-01 vs 2021-07-01 / 2021-10-01). The only file under the AT tests directory is a Tesla fixture YAML; it is not an executable test.

**Impact:** The metadata implies a level of verification that is not backed by executable regression coverage. A passing pipeline does not demonstrate that NoVA or motor tax calculations match current Austrian law.

**Required remediation:** Reconcile status/effective-date metadata and add executable tests for BEV exemption, ICE examples, boundary values, malus brackets, and the monthly-to-annual conversion. Have tax fixtures cite the official source and effective date used.

## Recommended remediation order

1. F-001: Implement real schema validation and tests.
2. F-003: Align the TCO engine and defaults; remove silent zero-cost fallbacks.
3. F-004 / F-005: Independently verify Austrian statutory rules and add executable tax regression tests.
4. F-002: Establish completeness gates and replace or clearly quarantine placeholder records.
5. Re-run the full pipeline and validate generated autopsies against known expected examples before calling the data layer production-ready.

## Audit limitations

This is a repository consistency and implementation audit, not a legal opinion or a full external fact-check of every vehicle specification. No tax rate, subsidy, vehicle specification, or price has been changed. In particular, the tax pack requires current official-source verification before any correction is proposed.
