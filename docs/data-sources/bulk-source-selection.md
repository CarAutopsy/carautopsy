# Bulk vehicle source selection — Austrian/EU market, 2016–2026

**Status:** Step 1 research and 20-record validation only. No full dataset downloaded, no catalog or production script modified, no source manifest changed, no retrieval/paid provider activated.
**Date:** 2026-11-21.
**Validator:** `scripts/validate_bulk_source.py`; sample: `docs/data-sources/sample/eea_at_2017_sample.tsv`.

## 1. Candidate comparison

| # | Candidate | Exact URL / endpoint | License | Coverage | Key fields | Format / size | Update / last updated |
|---|---|---|---|---|---|---|---|
| 1 | **EEA type-approval CO2 microdata** ("Monitoring of CO2 emissions from passenger cars") | Catalogue: https://www.eea.europa.eu/data-and-maps/data/co2-cars-emission-20 · viewer: https://co2cars.apps.eea.europa.eu/ · bulk via EEA Datashare public share (`/datashare/public.php/webdav/CO2_passenger_cars.csv`) | **CC BY 4.0** (catalogue licence: `https://creativecommons.org/licenses/by/4.0/`; some supporting documents CC BY-SA 3.0 IGO) | EU-27 + UK; IS since 2018, NO since 2019. Annual files 2010–2019 available as public shares (2016–2019 in scope). All fuel types incl. BEV/PHEV in later years. | `Mh` make, `Mk`/`MMS` model, `Va`/`Ve` variant, `Ct`/`Cr` class, `m (kg)` mass, `ep (KW)` power, `Ft` fuel type, `Ewltp`/`Enedc` CO2, `z (Wh/km)` EV consumption, `Erwltp` EV range, `W/At1/At2` dimensions. **No price, no liquid-fuel consumption.** | UTF-16LE **tab-separated** CSV despite `.csv` name; 1,749,558,422 bytes (~1.75 GB) for 2017 file; ~5.3 M rows | Annual; file on share last modified 2022-11-07, share metadata 2026-02-08 |
| 2 | **US EPA / DOE fuel economy bulk data** | https://www.fueleconomy.gov/feg/epadata/vehicles.csv (zipped: https://www.fueleconomy.gov/feg/epadata/vehicles.csv.zip) | U.S. Government work (EPA/DOE, administered by ORNL) — generally public domain; confirm attribution terms before commercial reuse | MY 1984–2026, US market only; all fuel types incl. BEV/PHEV; thousands of variants | `year`, `make`, `model`, `trany`, `fuelType1`, `mpge`, `range`, `evMotor`, `charge240`, `co2`, MPG. **No vehicle mass, no EU WLTP, no Austrian price.** | CSV 21,909,747 bytes; ZIP 2,228,192 bytes | **Updated 2026-11-04** (annual + corrections) |
| 3 | **EEA CO2 viewer / discodata API** | https://co2cars.apps.eea.europa.eu/ ; https://discodata.eea.europa.eu/ | CC BY 4.0 (EEA) | Current reporting years (WLTP era, 2020+), model/version level via viewer | Aggregated type-approval statistics; variant-level export not documented as a stable public bulk endpoint | Web UI / JSON, no documented bulk file | Near-real-time annual |
| 4 | **OpenDataSoft car registries** | https://data.opendatasoft.com/ (portal search, e.g. national vehicle-registration datasets) | Varies by dataset, commonly CC BY | Registration counts by make/model/year; Austria-specific portals exist | Registrations, make, model, year; **no variant power/mass/battery** | CSV/JSON API | Varies |
| 5 | **OEM public spec sheets** (Tesla, VW, BMW, …) | Individual OEM press sites | Proprietary; bulk download generally **not permitted** | Rich fields incl. price, battery, range | Complete but no stable bulk licence | HTML/PDF | Continuous |
| 6 | **Kaggle vehicle datasets** | kaggle.com/datasets/… | Mixed / frequently unclear; API token required | Unclear provenance | Often price + power, rarely mass | CSV | Unknown |

Candidates 5 and 6 are rejected: no legally clear bulk licence, and Kaggle access would require a token (secret) — both violate the project's data-rights policy and this mission's no-secret rule.

## 2. Recommendation

**Primary source: EEA type-approval CO2 microdata (candidate 1).**

Justification:
- It is the only candidate that supplies the **gate-critical fields** `power (kW)`, `mass (kg)`, fuel type and vehicle class at **variant/trim level** for EU/Austrian registrations (100% coverage in the 20-row sample).
- Licence is explicit and permissive (CC BY 4.0).
- Bulk access is a public, unauthenticated HTTP share; byte-range sampling works, so a 10–20 record validation needs no full download.
- It covers the Austrian market directly (`MS == "AT"` rows) across the annual files available for 2016–2019.

**Important limitation (proven, not assumed):** EEA microdata alone produces **0 gate-ready variants**. It has no price and no liquid-fuel consumption, and the 2017 file carries NEDC rather than WLTP CO2. For ICE variants the readiness gate therefore rejects every sampled row on `purchase_price_excl_vat_eur`, `extensions.fuel_consumption_l_100km` and `co2_wltp_gpkm`. Additionally, 2016–2019 registration years have no rules in the current AT tax pack (2025–2029), so statutory validation rejects them until either the tax pack is extended or the demo uses a supported year.

**Required companion inputs for STEP 2:** an owner-approved source for price and fuel consumption (EPA data can cross-check consumption but is US-market and has no mass; a documented CO2→L/100km proxy needs explicit owner approval), and a statutory year decision. No such proxy or rule change is made in this step.

## 3. Sample validation output (exact, reproducible)

Command: `python scripts/validate_bulk_source.py`

```
source: EEA CO2 passenger cars (public type-approval microdata)
sampled: 20 passed: 0 rejected: 20
field coverage %:
  variant_id: 100.0
  identity.make: 100.0
  identity.model: 100.0
  identity.powertrain: 100.0
  identity.vehicle_class: 100.0
  registration.first_registration_date: 100.0
  dimensions.max_permissible_mass_kg: 100.0
  performance.combustion_engine_power_w: 100.0
  performance.electric_motor_continuous_power_w: 0.0
  energy.consumption_wh_km: 0.0
  emissions.co2_wltp_gpkm: 0.0
  emissions.co2_nedc_gpkm: 100.0
  offers.purchase_price_excl_vat_eur: 0.0
  extensions.fuel_consumption: 0.0
rejection reasons:
  20x Motor-tax ICE rules unavailable for first-registration year 2017
  20x NoVA rules unavailable for first-registration year 2017
  20x emissions.co2_wltp_gpkm
  20x extensions.fuel_consumption_l_100km.real_world or wltp_combined must be a finite positive number
  20x offers[0].purchase_price_excl_vat_eur must be a finite positive number
```

Structural-only run (`python scripts/validate_bulk_source.py --no-taxes`) also yields 0/20, with only the three field-level gaps — confirming the source schema, not the tax pack, is the binding limitation.

Sample characteristics: 20 unique Austrian rows from the 2017 final-data file; fuel types DIESEL (32), PETROL (21), Diesel (6), NG-BIOMETHANE (1) across all collected rows; sampled rows are conventional ICE, so BEV-specific fields are 0% in this particular window.

## 4. Exact download / sampling instructions

The share token below is a **public EEA share token**, not a secret. No credentials were used or stored.

```bash
# 1. Dataset catalogue and licence
open https://www.eea.europa.eu/data-and-maps/data/co2-cars-emission-20
open https://co2cars.apps.eea.europa.eu/

# 2. Public share page for the 2017 final-data CSV
open https://sdi.eea.europa.eu/data/0a8985f6-af2d-44b7-ac88-a749da19a155
#    -> share token H6gQjNZ5nEWTs3S, file CO2_passenger_cars.csv

# 3. List the share WITHOUT downloading it (WebDAV PROPFIND)
curl -X PROPFIND -H 'Depth: 1' \
  https://sdi.eea.europa.eu/datashare/public.php/webdav/ \
  -u 'H6gQjNZ5nEWTs3S:'
#    -> CO2_passenger_cars.csv, 1,749,558,422 bytes, text/csv
#    -> README.md, monitoring metadata XML

# 4. Sample only (byte ranges; file is UTF-16LE tab-separated)
curl -u 'H6gQjNZ5nEWTs3S:' -H 'Range: bytes=3145728-3345727' \
  https://sdi.eea.europa.eu/datashare/public.php/webdav/CO2_passenger_cars.csv \
  -o sample.bin
python -c "print(open('sample.bin', encoding='utf-16').read()[:200])"

# 5. Validate the committed 20-record sample (offline)
python scripts/validate_bulk_source.py
```

Other annual share tokens found on the same catalogue page (public, token from each share page): 2016 final `Wx6A35C7yzc9Pis`, 2018 final `ytQ4LEdCA5ggcy7`, 2019 final `55xkXCtBCFTyTmx`. Full-year files are ~1–2 GB each; do **not** download them in Step 1.

EPA cross-check dataset (optional, 22 MB total): `https://www.fueleconomy.gov/feg/epadata/vehicles.csv` (updated 2026-11-04).

## 5. Realistic yield assessment for STEP 2

- Each annual EEA file contains millions of registration rows; Austrian rows are roughly 2–3% of the sample windows. Across 2016–2019 this is far more than 1,000 distinct make/model/variant combinations.
- **Unique, attested variants:** realistically 500–1,000 Austrian-relevant variants can be selected after deduplication on `(make, model, variant, power, mass, fuel type)`.
- **Gate-ready variants from EEA alone: 0** in the sampled window, for the field reasons above. Reaching the 500–1,000 target requires STEP 2 to add an owner-approved price/consumption source and a statutory-year decision, and to prove readiness on the resulting merged records with this same script pattern.

## 6. STEP 2 instructions (not started)

1. Obtain owner decision on (a) which statutory years the pilot supports and (b) whether a CO2→fuel-consumption proxy and a price source are acceptable as attested derived inputs. Record the decision in an issue before coding.
2. Extend `validate_bulk_source.py` with a second, clearly-attributed input adapter; never fabricate a price or WLTP value.
3. Run a full-field coverage report over a larger (still sampled) window before any full download; require >90% coverage on every gate-required field.
4. Generate catalog records as a **proposal artifact** into `docs/data-sources/` only; do not write `catalog/variants/` until owner approval and exact-head CI.
5. Re-run `validate_catalog.py` and `repo_audit.py` on the proposal, then deliver a separate PR for owner review. No activation, manifest change or publication.
