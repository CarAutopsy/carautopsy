# Price-source plan — Austrian/EU verified pricing for 2017-2019 vehicles

**Status:** Research only. No catalog write, no retrieval/paid-provider activation, no gate change.
**Date:** 2026-11-21.
**Scope:** the gate-critical price input for the 154-row 2018 WLTP Austrian sample and the next
100-1,000 variants.
**Problem evidence (measured):** all 154 sampled records fail one gate field,
`offers[0].purchase_price_excl_vat_eur must be a finite positive number` (145 rejected). The 9
structural passes are `price_pending: true`; no price was fabricated. EEA type-approval microdata has
**no price field at all**.

## 1. Candidate comparison

### A. Curated OEM MSRP datasets (historical price lists)
- **Source URL:** OEM price-list archives / press portals, e.g. manufacturer model pages and PDF
  price lists; no stable bulk endpoint was identified.
- **License / terms:** proprietary; bulk download and redistribution are generally not permitted.
  Individual document citation with attribution may be possible per OEM, but must be confirmed.
- **Coverage:** model/trim level for the models an OEM still publishes; 2017-2019 archives are often
  removed or replaced by current configurators.
- **Fields:** list price (usually incl. VAT), model, trim, engine, date of validity, sometimes market.
  Excl-VAT price must be derived from an explicitly documented VAT rate (20% in AT for the period),
  and that derivation must be recorded.
- **Historical availability:** **poor for 2017-2019**; archived PDFs are scattered and not indexed as
  a dataset.
- **Update cadence:** OEM-driven, irregular; no SLA.
- **Cost:** no licence fee, high curation effort; permission risk.
- **Suitability for 2017-2019 Austrian vehicles:** medium-low — usable when a dated official AT
  price list is located and cited, but not a bulk source.

### B. Public vehicle-listing aggregates (asking-price portals)
- **Source URL:** e.g. `https://www.autoscout24.at/`, `https://www.mobile.de/` (portal terms apply).
- **License / terms:** listing portals' terms of service generally **prohibit systematic scraping and
  bulk redistribution**; an open data licence was not identified. API access, where offered, is
  commercial and requires credentials (a secret) — excluded by this project's rules.
- **Coverage:** large current stock; rich model/trim text; Austrian market present.
- **Fields:** asking price, mileage, year, powertrain, model/trim strings; **asking price is not MSRP**
  and is not a verified list price.
- **Historical availability:** poor — current listings only; price history is not exposed.
- **Update cadence:** continuous, uncontrolled.
- **Cost:** free web UI; no compliant bulk licence; API would be paid/credentialed.
- **Suitability for 2017-2019 Austrian vehicles:** low — wrong price semantics (asking vs list),
  no verifiable historical snapshot, and licence/ToS conflict. **Rejected.**

### C. Official price lists or regulatory datasets
- **Source URL:** Austrian/EU official publications, e.g. BMF (`https://www.bmf.gv.at/`), Statistik
  Austria (`https://www.statistik.at/`), EU/Eurostat (`https://ec.europa.eu/eurostat`).
- **License / terms:** official publications are typically reusable with attribution under national
  open-data rules, but **none of these publishes variant-level MSRP**; NoVA/motor-tax tables (used in
  `at-rules-v1.json`) are tax rules, not prices.
- **Coverage:** n/a for vehicle prices.
- **Fields:** tax rates, registration counts, aggregate statistics; no `purchase_price_excl_vat_eur`.
- **Historical availability:** good for tax tables; none for MSRP.
- **Update cadence:** official, periodic.
- **Cost:** free.
- **Suitability for 2017-2019 Austrian vehicles:** none as a price source; useful only as statutory
  context. **Rejected as a price source.**

### D. (bonus) Project-owned curated price evidence file
- **Source URL:** versioned file under `docs/data-sources/price-evidence/v1.json` with one row per
  matched variant, each row citing the actual source document URL and licence.
- **License / terms:** project-owned compilation; inherits the licence of each cited documents; only
  rows with a verified citation are accepted.
- **Coverage:** exactly the variants with a documented, dated price; grows with curator effort.
- **Fields:** the full price contract in section 3 plus the match key in section 4.
- **Historical availability:** as good as the cited document; dated rows survive later model changes.
- **Update cadence:** versioned per batch.
- **Cost:** curator time; no licence fee.
- **Suitability:** high as a *container* for evidence, not a source by itself.

## 2. Recommendation

**No compliant bulk Austrian MSRP source is currently available.** The mission's recommended-source
question therefore has an explicit negative answer: there is no bulk source that is simultaneously
licensed for reuse, variant-level, historically accurate for 2017-2019, and free of credential or
scraping terms that violate this project's rules.

Interim policy — unchanged by this research:
- Keep `price_pending: true` and `purchase_price_excl_vat_eur: null` where no verified price exists.
- Keep the readiness gate rejecting such records; never treat `price_pending` as a price.
- Accept a price only from an owner-approved, dated, attributable source recorded as a versioned row
  in a curated price-evidence file (candidate D), one row per matched variant.
- Re-evaluate an OEM or regulatory bulk source only if the owner supplies a documented licence that
  permits reuse; candidates B and C are rejected on licence/semantics grounds above.

Expected coverage today: **0 of 154** records can receive a verified price. The 9 structural passes
remain `price_pending` and are not gate-ready.

## 3. Exact required price fields

A proposal may carry a verified price only when **all** of the following are present and valid:

| Field | Requirement |
|---|---|
| `offers[0].purchase_price_excl_vat_eur` | finite number > 0; excl. VAT; not inferred from a range midpoint |
| `offers[0].price_date` | ISO date the price was valid (`YYYY-MM-DD`) |
| `offers[0].currency` | `EUR` |
| `offers[0].market` | exact market code, e.g. `AT` |
| `offers[0].source_url` | http(s) URL of the price document |
| `offers[0].license` | licence/terms of that document |
| `offers[0].retrieved_at` | ISO date the evidence was retrieved |
| `price.price_pending` | `false` |
| `price.match` | object with the matched fields and uncertainty note from section 4 |

If the source publishes an incl-VAT price, the VAT conversion must be stored as an explicit derived
field with the rate, date and formula; the converted value is still a verified price only if the
owner accepts that documented derivation. No price is reconstructed from memory or from an
unrelated market.

## 4. Price matching and uncertainty handling

1. **Match key (all required):** `make`, `model`, `variant`, `powertrain`, `model_year`, `market`
   (AT). Use the resolved consumer identity from `identity-resolution-plan.md`, not the raw EEA
   `make == model` strings.
2. **Exact match only.** A candidate price row is accepted only if all six key fields match exactly.
   No fuzzy trim inference, no "same powertrain, similar model" substitution.
3. **Uncertainty rules:**
   - if several rows match with different prices, refuse and record the conflict;
   - if the price date is not within the model year / validity window, refuse;
   - if the source is an asking price rather than a list price, refuse;
   - if any key field is missing or unresolved (identity is `requires_manual_curation`), refuse.
4. **Record the match** in `price.match` with `matched_fields`, `source_url`, `price_date`,
   `uncertainty = "none" | "refused"` and, on refusal, a plain-text `reason`.
5. **Fail closed.** Missing price evidence is a gate rejection, not a null-with-pass. The reporting
   script implements exactly this: 0 verified prices when the evidence file is absent.

## 5. Owner decisions required before any price ingestion

1. Supply or approve a dated AT list-price document with reuse terms, or confirm that all
   `price_pending` records stay out of the catalog.
2. Approve the incl-VAT-to-excl-VAT derivation policy (rate/date/formula) if such a source is used.
3. Confirm that no price is ingested while `price_pending != false`.
