# Pilot Batch 001 — Austrian price evidence dossier

**Status:** RESEARCH ONLY. No catalog record was added, changed, or removed; no staging
record was created; no live retrieval, provider call, secret, workflow, CI, gate, or
approval change was made. Owner approval remains required for implementation,
staging, and any catalog PR.

- **Branch:** `feat/pilot-approximate-price-coverage`
- **Base commit:** `bbffb53b014fe335e8d9963fe94cc80cb83c2683` (PR #147 head at research time)
- **Prepared:** 2026-11-22
- **Mode:** offline research notes and committed source references only

## 1. Objective and boundary

Build the source dossier and candidate-price matrix for the 25 models in
`docs/operations/PILOT_BATCH_001.md`, applying the resolution order in
`docs/data-sources/approximate-price-protocol-v1.md`. This document and its
companion `pilot-batch-001-price-candidates.json` are research artifacts only.
They do not authorize ingestion, a staging batch, or catalog publication.

Scope and acceptance rules were read from:

- `docs/operations/PILOT_BATCH_001.md`
- `docs/data-sources/approximate-price-protocol-v1.md`
- `docs/operations/COVERAGE_SCOREBOARD.md`
- `docs/operations/AUSTRIA_PRIORITY_BACKLOG.md`

## 2. Evidence inventory (all local, committed)

| Source | What it contributes |
|---|---|
| `docs/data-sources/identity-map/v1.json` | 58 identity rows; 2018 Austrian EEA sample resolved to consumer models |
| `docs/data-sources/price-evidence/v1.json` | 36 price rows; all `model_level` precision; AT market, EUR |
| `docs/data-sources/price-evidence/unresolved.json` | 22 unresolved keys, all `no_model_level_price_source` (12 Kodiaq + 10 Karoq) |
| `docs/data-sources/research-coverage-report.json` | identity 154/154 resolvable; price 114 gate-passed, 40 `no_exact_price_row`; no compliant bulk source |
| `docs/data-sources/harvest-price-log.json` | 11 archived price-list candidates; Skoda AT lists plus one Nissan AT Leaf list |
| `docs/data-sources/price-source-plan.md` | No compliant bulk Austrian MSRP source; VAT/derivation rules; owner decisions |
| `docs/data-sources/bulk-ingestion.md` | Records Kodiaq/Karoq as unresolved after exhaustive search |
| `docs/data-sources/statutory/at-rules-v1.json` | AT VAT context is not stored here; NoVA BEV exemption and hybrid exclusion, motor-tax dates |

The committed price evidence covers only **Octavia, Fabia, Superb, Rapid, Scala**
(Skoda AT price lists) and **Nissan Leaf** (AT price list). Of the 25 pilot models,
only **Octavia** and **Fabia** have committed price rows.

## 3. Method and tier decisions

Each model was checked against the committed identity and price files. No price,
specification, VIN, identity field, FX rate, or date was invented. Numeric fields
without evidence are `null` in the JSON matrix; `0` is not used as a placeholder.

Octavia and Fabia are classified **`approximate`**, not `verified`, even though
their prices are dated and attributable Austrian list prices. Reason: the evidence
is model-level rather than variant-specific, confidence is `low`, and `reviewed_by`
is `automated-model-level-harvest-v1 (pending owner review)`. The protocol reserves
`verified` for exact, dated, attributable Austrian evidence eligible for full TCO.

No record was assigned `derived`, `approximate_cross_market`, or `range`: no
approved derivation rule, FX rate, or credible low/high range exists in the
committed evidence.

## 4. Austrian VAT and pricing basis note

- Austrian price lists in the committed evidence state prices **inkl. MwSt.**
  (VAT included). The standard Austrian VAT rate for the 2017–2019 period is
  **20%**, as recorded in `docs/data-sources/price-source-plan.md`.
- The committed price rows carry both values. The excl-VAT amount was derived as
  `incl-VAT / 1.20`; for Octavia, `22,630.00 / 1.20 = 18,858.33`, and for Fabia,
  `11,480.00 / 1.20 = 9,566.67`. The derivation is recorded in each row's
  `vat_treatment` / `vat_rate_used` fields.
- The candidate matrix stores the **incl-VAT source value** in `price_value` with
  `vat_basis: "incl_vat"` and the derived excl-VAT value in
  `excl_vat_value_derived`, with the formula in `adjustment_method`.
- Future evidence must state its basis explicitly. Never compare an incl-VAT
  source directly with an excl-VAT source, and never mix VAT bases in one TCO
  result.

## 5. Cross-market adjustment policy (draft — not applied)

No cross-market candidate is proposed in this dossier because no FX rate or
adjustment was retrieved offline. If the owner authorizes such research later,
each candidate must record:

1. Source market and exact source URL plus publication/retrieval date.
2. Source currency and an FX rate with its date and provider (e.g., ECB reference rate).
3. Tax differences: source-market VAT, Austrian 20% VAT, NoVA treatment, and any
   registration or luxury tax in the source market.
4. Equipment/specification differences between the source-market trim and the
   intended Austrian trim.
5. A written adjustment method and a confidence level of `low` or `medium`.
6. `review_required: true` and a correction-queue entry.

A foreign list price must never be relabeled as an Austrian price. Dealer asking
prices, used-car prices, and marketplace listings are not new-car MSRP evidence.

## 6. Findings — all 25 models

Tier legend: `approx` = approximate Austrian list-price proxy; `unavail` = no
defensible proxy in committed evidence. "Years" means committed model-year
evidence, not pilot-priority metadata.

| # | Model | Priority | Years | Powertrains evidenced | Tier | Price (incl VAT) | Source date | Confidence |
|---:|---|---|---|---|---|---:|---|---|
| 1 | Škoda Octavia | 2025 top seller | 2018 | diesel 13, petrol 8 | approx | EUR 22,630.00 | 2018-11-30 | low |
| 2 | Volkswagen Golf | 2025 top seller | — | — | unavail | — | — | — |
| 3 | BMW X1 | 2025 top seller | — | — | unavail | — | — | — |
| 4 | Seat Ibiza | 2025 top seller | — | — | unavail | — | — | — |
| 5 | Toyota Yaris | 2025 top seller / hybrid | — | — | unavail | — | — | — |
| 6 | Dacia Sandero | 2025 top seller | — | — | unavail | — | — | — |
| 7 | Dacia Duster | 2025 top seller | — | — | unavail | — | — | — |
| 8 | Škoda Fabia | 2025 top seller | 2018 | petrol 5 | approx | EUR 11,480.00 | 2019-03-01 | low |
| 9 | Dacia Bigster | 2025 top seller | — | — | unavail | — | — | — |
| 10 | Volkswagen Tiguan | high-volume SUV | — | — | unavail | — | — | — |
| 11 | Volkswagen T-Roc | high-volume SUV | — | — | unavail | — | — | — |
| 12 | Škoda Kodiaq | SUV; unresolved price | 2018 | diesel 12 | unavail | — | — | — |
| 13 | Škoda Karoq | SUV; unresolved price | 2018 | petrol 6, diesel 4 | unavail | — | — | — |
| 14 | Audi A3 | premium compact | — | — | unavail | — | — | — |
| 15 | Audi Q3 | premium SUV | — | — | unavail | — | — | — |
| 16 | BMW 3 Series | premium sedan | — | — | unavail | — | — | — |
| 17 | Mercedes-Benz GLC | premium SUV | — | — | unavail | — | — | — |
| 18 | Hyundai Tucson | SUV | — | — | unavail | — | — | — |
| 19 | Kia Sportage | SUV | — | — | unavail | — | — | — |
| 20 | Toyota Yaris Cross | hybrid SUV | — | — | unavail | — | — | — |
| 21 | Toyota Corolla | hybrid | — | — | unavail | — | — | — |
| 22 | Volkswagen ID.3 | BEV | — | — | unavail | — | — | — |
| 23 | Škoda Enyaq | BEV | — | — | unavail | — | — | — |
| 24 | Tesla Model Y | BEV | — | — | unavail | — | — | — |
| 25 | Volvo XC40 / EX40 | premium BEV | — | — | unavail | — | — | — |

Full per-model objects, including source URLs, gaps, and recommended actions,
are in `docs/research/pilot-batch-001-price-candidates.json`.

## 7. Detailed findings

### 7.1 Škoda Octavia

- 21 committed 2018 AT identity rows: 13 diesel, 8 petrol.
- 21 committed price rows all cite the archived `octavia-preisliste-12-2018.pdf`
  (skoda.at, snapshot dated 2018-11-30).
- Incl-VAT EUR 22,630.00; derived excl-VAT EUR 18,858.33; `price_precision`
  `model_level`; `confidence` `low`; owner review pending.
- Not variant-specific: no evidence for the dominant diesel/petrol trim prices.

### 7.2 Škoda Fabia

- 5 committed 2018 AT identity rows, all petrol.
- 5 committed price rows cite the archived `FABIA20-Streuer-03-2019.pdf`
  (skoda.at, dated 2019-03-01).
- Incl-VAT EUR 11,480.00; derived excl-VAT EUR 9,566.67; same model-level and
  pending-review limitations as Octavia.

### 7.3 Kodiaq and Karoq — evidence trail reopened

- Kodiaq: 12 committed 2018 identity rows, all diesel; 12 unresolved price keys.
- Karoq: 10 committed 2018 identity rows (6 petrol, 4 diesel); 10 unresolved price keys.
- `docs/data-sources/price-evidence/unresolved.json` gives all 22 keys reason
  `no_model_level_price_source` and detail "No dated archived AT price list found
  for this consumer model".
- `docs/data-sources/harvest-price-log.json` found 11 archived AT price lists;
  none covers Kodiaq or Karoq. `docs/data-sources/bulk-ingestion.md` records them
  as unresolved after exhaustive search.
- **Conclusion:** both remain `unavailable` in committed evidence. Reopening
  requires a dated, attributable Austrian list-price document for the specific
  consumer model and trim, plus owner review of VAT basis and relevance. No
  cross-market or inferred price is proposed.

### 7.4 Remaining 21 models

No committed identity or price evidence exists for these models. The 2025
top-seller and priority labels come from the pilot documents and owner brief;
they are registration-priority metadata, not price or specification evidence.
No 2020–2026 model-year evidence exists locally.

## 8. Correction queue

Every candidate is tracked. Counts: `approximate` 2, `unavailable` 23.

- **Upgrade candidates (approximate → verified on new evidence):** Octavia, Fabia.
  Required: dated attributable source, variant-level match, explicit market and
  VAT basis, reviewer approval, recorded change reason.
- **Reopen-either-trail (identity exists, price unresolved):** Kodiaq, Karoq.
- **Research-required (no committed evidence):** Golf, X1, Ibiza, Yaris, Sandero,
  Duster, Bigster, Tiguan, T-Roc, A3, Q3, 3 Series, GLC, Tucson, Sportage,
  Yaris Cross, Corolla, ID.3, Enyaq, Model Y, XC40 / EX40.

## 9. Coverage gap list

No defensible price proxy is available for 23 of 25 models: Kodiaq, Karoq, and
all 21 models in section 7.4. The highest-impact gaps are the 2025 top sellers
Golf, X1, Ibiza, Yaris, Sandero, Duster, and Bigster. Against the scoreboard's
95% price-quality target, committed evidence currently supports 2/25 models
(8%) at any usable price tier.

## 10. TCO-readiness forecast

- **Octavia and Fabia:** could become *provisionally* TCO-ready once the
  price-tier schema, validation, and provisional-output rules are implemented
  and owner-approved. Other TCO gates (statutory rules, mass, power, offer
  fields) are not evaluated in this research and remain unverified here.
- **Kodiaq and Karoq:** may retain identity/specification evidence but must be
  excluded from price-dependent TCO outputs until an attributable price is found.
- **Remaining 21:** not TCO-ready; no price evidence and no pilot record exist.
- No record in this dossier is fully TCO-ready.

## 11. Source leads from the owner brief (unfetched — not evidence)

These URLs were supplied as candidate starting points. They were **not** fetched
or verified in this offline session and carry no evidentiary weight here:

- Mercedes-Benz Austria configurator: `https://www.mercedes-benz.at/passengercars/configurator.html`
- Audi Austria configurator (owner-brief reference)
- Volkswagen Austria current model pricing (owner-brief reference)
- Statistik Austria new-car registrations (owner-brief reference)
- de-motor Austria market note (owner-brief reference)
- ARBÖ / EuroCarIndex valuation notes (owner-brief reference; valuation and
  asking-price sources, not new-car MSRP)

The 284,978 new passenger-car registrations figure and the 2025 top-seller list
are likewise owner-brief/pilot-document context, not independently verified data.

## 12. Limitations and owner decisions

Limitations:

- Offline only; no source URL was opened and no live price was retrieved.
- Committed price evidence is limited to 2018/2019 At samples; no 2020–2026 evidence.
- No registration counts, FX rates, body styles, or powertrain-share statistics
  were independently verified.
- Model-level prices are not variant-level prices.

Owner decisions required:

1. Whether to authorize live, owner-controlled source research or supply dated AT
   price documents for the 23 gap models.
2. Whether these two research files belong in PR #147 or a separate documentation PR.
3. Approval of the future schema/ingestion implementation before any staging batch.
4. Continued pause on Hive, backlog dispatch, ingestion, gates, secrets, and providers.

## 13. Safeguards

No `catalog/variants/` write, no staging record, no workflow/CI change, no gate or
secret change, no provider or network access, no invented value, and no catalog PR
was made by this research task.
