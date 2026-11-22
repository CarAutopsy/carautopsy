# Pilot gap price research — Batch 001 gaps and Batch 002 EV expansion

**Status:** RESEARCH AND DOCUMENTATION ONLY. No catalog record, staging record,
workflow, CI, gate, secret or provider configuration was changed. No PR was
opened and nothing was merged.

- **Branch:** `feat/pilot-approximate-price-coverage`
- **Base:** PR #147 head `a26a5b7` at research start; research commit follows this dossier
- **Retrieval date for all live pages:** 2026-11-22
- **Mode:** bounded manual web research using public pages; no API key, no automated
  scraping, no workflow retrieval, no paid provider

## 1. Method and source hierarchy

Read first, as instructed: `docs/data-sources/approximate-price-protocol-v1.md`,
`docs/data-sources/external-source-integration.md`,
`docs/operations/COVERAGE_SCOREBOARD.md`,
`docs/operations/AUSTRIA_PRIORITY_BACKLOG.md`,
`docs/operations/PILOT_BATCH_001.md`,
`docs/operations/PILOT_BATCH_002_EV_EXPANSION.md`,
`docs/research/pilot-batch-001-price-research.md`,
`docs/research/pilot-batch-001-price-candidates.json`,
`data/sources/registry.json`.

Evidence order actually applied:

1. **Austrian manufacturer website / official AT page** — used for Volkswagen
   (`vw_austria`), XPeng (`xpeng_austria`) and the carried-over committed Skoda
   price-list rows (`committed_price_evidence_v1`).
2. **Dated Austrian dealer/price source** — BYD Austria dealer page (`denzel_at`)
   was consulted as a cross-check; its displayed prices are bonus-inclusive and
   were not admitted as MSRP.
3. **EV Database web portal** — **no observations recorded** (see section 7).
4. **One Auto API** — not called; classified in section 8.
5. **Comparable EU/EEA source** — no cross-market price was used in this pass.
6. **Range** — none recorded.
7. **`unavailable`** — used where no defensible price proxy exists.

Every URL in the matrix was actually fetched during this session except the two
committed Skoda archive URLs, which are carried verbatim from the prior research
file and are marked with their original source dates.

## 2. Austrian VAT and pricing-basis rules

- Austrian standard VAT is **20%**. Volkswagen Austria pages state prices include
  **NoVA and 20% MwSt.** (plus freight where noted); XPeng Austria states
  *"Alle Angaben inkl. 20% Ust."*; BYD Austria states prices are *"inkl. MwSt,
  NoVA samt §6aNoVAG"*.
- Matrix `vat_basis` is `incl_vat` for every admitted price. No excl-VAT value was
  computed in this pass because no approved derivation rule for current prices
  was supplied by the owner.
- **Bonus-adjusted prices were excluded.** VW's "Preis inkl. Boni ab" figures,
  BYD's "ab €X inkl. BYD LEASE-, Versicherungs- & Eintauschbonus" figures, and
  XPeng monthly leasing rates are not base MSRPs. For XPeng, the separate
  *Kaufpreis / UVP* printed in the leasing footnote was used; the monthly rate was not.
- A used-car asking price or a monthly leasing payment was never used as a purchase price.
- Approximate records retain the owner-specified research field names and additionally carry the protocol-named aliases `price_value`, `price_source_url`, `price_source_date` and `price_confidence` so protocol-required provenance is directly discoverable. Unavailable records are unchanged.

## 3. Cross-market adjustment policy

No cross-market price was admitted. Had one been needed, the required record would
be: source market, exact URL and date, source currency, FX rate with date and
provider, VAT and NoVA treatment in both markets, equipment/trim differences, a
written adjustment method, `confidence` of `low` or `medium`, and
`review_required: true`. No FX rate was retrieved, so no conversion was attempted.

## 4. Per-model findings

| # | Brand | Model | Variant | Tier | Price (EUR incl. VAT) | Source | Retrieval / source date |
|---:|---|---|---|---|---:|---|---|
| 1 | Škoda | Octavia | model-level AT price-list entry | approximate | 22,630.00 | committed_price_evidence_v1 | 2018-11-30 |
| 2 | Škoda | Fabia | model-level AT price-list entry | approximate | 11,480.00 | committed_price_evidence_v1 | 2019-03-01 |
| 3 | Volkswagen | Golf | Golf (Preis ab) | approximate | 26,790.00 | vw_austria | 2026-11-22 |
| 4 | Volkswagen | Tiguan | Tiguan (Preis ab) | approximate | 37,490.00 | vw_austria | 2026-11-22 |
| 5 | Volkswagen | T-Roc | T-Roc (Preis ab) | approximate | 30,390.00 | vw_austria | 2026-11-22 |
| 6 | Volkswagen | ID.3 | ID.3 Neo Trend | approximate | 34,490.00 | vw_austria | 2026-11-22 |
| 7 | BMW | X1 | — | unavailable | — | none | — |
| 8 | Seat | Ibiza | — | unavailable | — | none | — |
| 9 | Toyota | Yaris | — | unavailable | — | none | — |
| 10 | Dacia | Sandero | — | unavailable | — | none | — |
| 11 | Dacia | Duster | — | unavailable | — | none | — |
| 12 | Dacia | Bigster | — | unavailable | — | none | — |
| 13 | Škoda | Kodiaq | — | unavailable | — | none | — |
| 14 | Škoda | Karoq | — | unavailable | — | none | — |
| 15 | Audi | A3 | — | unavailable | — | none | — |
| 16 | Audi | Q3 | — | unavailable | — | none | — |
| 17 | BMW | 3 Series | — | unavailable | — | none | — |
| 18 | Mercedes-Benz | GLC | — | unavailable | — | none | — |
| 19 | Hyundai | Tucson | — | unavailable | — | none | — |
| 20 | Kia | Sportage | — | unavailable | — | none | — |
| 21 | Toyota | Yaris Cross | — | unavailable | — | none | — |
| 22 | Toyota | Corolla | — | unavailable | — | none | — |
| 23 | Škoda | Enyaq | — | unavailable | — | none | — |
| 24 | Volvo | XC40 / EX40 | — | unavailable | — | none | — |
| 25 | Tesla | Model 3 | — | unavailable | — | none | — |
| 26 | Tesla | Model Y | — | unavailable | — | none | — |
| 27 | Tesla | Model S | — | unavailable | — | none | — |
| 28 | Tesla | Model X | — | unavailable | — | none | — |
| 29 | Tesla | Cybertruck | — | unavailable | — | none | — |
| 30 | XPeng | G6 | G6 RWD Standard Range | approximate | 43,600.00 | xpeng_austria | 2026-11-22 |
| 31 | XPeng | G9 | G9 RWD Standard Range | approximate | 59,600.00 | xpeng_austria | 2026-11-22 |
| 32 | XPeng | P7+ | P7+ RWD Standard Range | approximate | 47,600.00 | xpeng_austria | 2026-11-22 |
| 33 | XPeng | L03 | L03 RWD Standard Range | approximate | 36,600.00 | xpeng_austria | 2026-11-22 |
| 34 | XPeng | X9 | X9 FWD Standard Range | approximate | 78,600.00 | xpeng_austria | 2026-11-22 |
| 35 | XPeng | G9L | G9L Long Range 2WD 7-seat Ultra | approximate | 75,600.00 | xpeng_austria | 2026-11-22 |
| 36 | XPeng | L05 | — | unavailable | — | none | — |
| 37 | BYD | Dolphin | — | unavailable | — | byd_austria | 2026-11-22 |
| 38 | BYD | Dolphin Surf | — | unavailable | — | byd_austria | 2026-11-22 |
| 39 | BYD | Atto 3 | — | unavailable | — | byd_austria | 2026-11-22 |
| 40 | BYD | Seal | — | unavailable | — | byd_austria | 2026-11-22 |
| 41 | BYD | Seal U | — | unavailable | — | byd_austria | 2026-11-22 |
| 42 | BYD | Seal U DM-i | — | unavailable | — | byd_austria | 2026-11-22 |
| 43 | BYD | Tang | — | unavailable | — | byd_austria | 2026-11-22 |
| 44 | BYD | Sealion 7 | — | unavailable | — | byd_austria | 2026-11-22 |
| 45 | BYD | Han | — | unavailable | — | byd_austria | 2026-11-22 |
| 46 | BYD | Sealion 8 | — | unavailable | — | byd_austria | 2026-11-22 |
| 47 | BYD | eMAX 7 | — | unavailable | — | byd_austria | 2026-11-22 |
| 48 | BYD | M3 | — | unavailable | — | byd_austria | 2026-11-22 |
Tier totals: **12 approximate**, **36 unavailable**.
Source-ID distribution: `none` 24, `byd_austria` 12, `xpeng_austria` 6, `vw_austria` 4, `committed_price_evidence_v1` 2.

### 4.1 Models with a usable Austrian price candidate

- Škoda Octavia
- Škoda Fabia
- Volkswagen Golf
- Volkswagen Tiguan
- Volkswagen T-Roc
- Volkswagen ID.3
- XPeng G6
- XPeng G9
- XPeng P7+
- XPeng L03
- XPeng X9
- XPeng G9L

Key detail:

- **Golf / Tiguan / T-Roc / ID.3** — official VW Austria model pages, base "Preis ab"
  incl. VAT and NoVA, retrieved 2026-11-22. ID.3 is mapped to the current Austrian
  "ID.3 Neo" name with the priced variant recorded as "ID.3 Neo Trend" (€34,490;
  50 kWh net battery per page; WLTP up to 629 km across the range; DC up to 183 kW;
  ~29 min 10–80%). Bonus prices were excluded.
- **XPeng G6 €43,600 · L03 €36,600 · P7+ €47,600 · G9 €59,600 · X9 €78,600 · G9L €75,600**
  — each from the model's own Austrian page, where the leasing footnote prints an
  indicative *Kaufpreis*. All include 20% USt and carry an offer validity date.
  G9L is included because an Austrian model page and configurator are documented.
  L03 explicitly states 10–80% in 20 min; G9/G6/P7+ state 20–80% in 10 min, which
  was **not** written into the 10–80% field.
- **Octavia / Fabia** — carried from the committed 2018/2019 Austrian price-list
  evidence; still model-level, low confidence, owner review pending.

### 4.2 BYD findings

BYD Austria lists current passenger models (Dolphin Surf, Dolphin, ATTO 3 EVO,
Seal, Seal U, Seal U DM-i, Sealion 7, Tang) and official "Preisliste & Ausstattung"
PDFs under `/downloads`. Displayed "ab" prices are explicitly bonus-inclusive
promotional prices, so they were **not** admitted as base MSRP. Directly displayed
WLTP ranges and charging times were retained as specification context (e.g.,
Seal 570 km / 30–80% 26 min; Sealion 7 502 km / 30–80% 18 min; Tang 530 km /
30–80% 30 min; ATTO 3 EVO 510 km / 10–80% 25 min). Sealion 8, eMAX 7, M3 and Han
had no documented current Austrian passenger-car offering in this pass.

### 4.3 Tesla findings

Tesla Austria (`https://www.tesla.com/de_AT` and `/de_AT/model3`) returned HTTP 403
on both attempts. No price or specification was observed, so Model 3, Model Y,
Model S and Model X remain `unavailable`. Cybertruck has no documented Austrian
offering or EU import pathway in this pass.

### 4.4 Remaining Batch 001 gaps

No defensible Austrian price was retrieved for:
- BMW X1
- Seat Ibiza
- Toyota Yaris
- Dacia Sandero
- Dacia Duster
- Dacia Bigster
- Škoda Kodiaq
- Škoda Karoq
- Audi A3
- Audi Q3
- BMW 3 Series
- Mercedes-Benz GLC
- Hyundai Tucson
- Kia Sportage
- Toyota Yaris Cross
- Toyota Corolla
- Škoda Enyaq
- Volvo XC40 / EX40
Kodiaq/Karoq retain their earlier unresolved status: 22 committed unresolved price
keys and no AT price list in the committed harvest. Toyota AT model path returned
404; BMW Austria timed out. Other brands were not retrieved in this bounded pass.

## 5. Evidence gaps

- No base-price PDF was parsed for BYD; the official Austrian price lists exist as
  URLs but require manual owner review.
- Tesla Austria blocks automated page retrieval (HTTP 403).
- EV Database and general web search were unavailable in this environment.
- No 2020–2026 model-year price evidence exists in the committed repository.
- No variant-level (trim/engine) price was obtained for any admitted candidate;
  all 12 approximate values are model-level entry prices.
- No FX rate or cross-market adjustment was obtained.

## 6. Correction queue

All 48 candidates remain in the correction queue.

- **Approximate, owner review required (12):** Škoda Octavia, Škoda Fabia, Volkswagen Golf, Volkswagen Tiguan, Volkswagen T-Roc, Volkswagen ID.3, XPeng G6, XPeng G9, XPeng P7+, XPeng L03, XPeng X9, XPeng G9L.
  Correction requires a dated attributable source, explicit market and VAT basis,
  reviewer approval and a recorded change reason.
- **Unavailable (36):** BMW X1, Seat Ibiza, Toyota Yaris, Dacia Sandero, Dacia Duster, Dacia Bigster, Škoda Kodiaq, Škoda Karoq, Audi A3, Audi Q3, BMW 3 Series, Mercedes-Benz GLC, Hyundai Tucson, Kia Sportage, Toyota Yaris Cross, Toyota Corolla, Škoda Enyaq, Volvo XC40 / EX40, Tesla Model 3, Tesla Model Y, Tesla Model S, Tesla Model X, Tesla Cybertruck, XPeng L05, BYD Dolphin, BYD Dolphin Surf, BYD Atto 3, BYD Seal, BYD Seal U, BYD Seal U DM-i, BYD Tang, BYD Sealion 7, BYD Han, BYD Sealion 8, BYD eMAX 7, BYD M3.
  Reopen only with a new dated Austrian price document or a documented, defensible
  cross-market adjustment.

## 7. EV Database disposition

EV Database has no authorized API here and must be used manually. In this pass the
portal homepage exceeded the fetch size limit (5 MB) and the web-search integration
returned HTTP 402, so **no EV Database vehicle page was observed and no EV Database
observation is recorded**. No URL, price, battery, range or charging figure is
attributed to `ev_database`. Per `data/sources/registry.json` its allowed price
tiers are `approximate` or `range`, never `verified`; any later observation must
record exact page URL, retrieval date, displayed price, currency, battery, WLTP,
efficiency, DC charging, 10–80% time, body style, weight and drivetrain.

## 8. One Auto API disposition

No API call was made and no key was requested, displayed, logged or committed.
From `data/sources/registry.json`, the source has `market_scope: ["to_be_verified"]`,
`status: enabled_pending_adapter`, and a note that Austrian market coverage and
permitted price use must be verified before any price field is ingested. It is
therefore classified **`not_applicable_for_price` (enrichment / cross-check only)**
until the owner documents Austrian identification, market specification and pricing
coverage plus an explicitly authorized bounded endpoint. No price tier is derived
from it in this matrix.

## 9. Coverage-gap list

36 of 48 researched candidates have no defensible price proxy.
Highest-impact gaps among 2025 top sellers: BMW X1, Seat Ibiza, Toyota Yaris,
Dacia Sandero, Dacia Duster, Dacia Bigster. Additional high-impact gaps: Audi A3/Q3,
BMW 3 Series, Mercedes-Benz GLC, Hyundai Tucson, Kia Sportage, Toyota Yaris Cross,
Toyota Corolla, Škoda Enyaq, Volvo XC40/EX40, all Tesla models, and all 12 BYD models.

## 10. TCO-readiness forecast

- The 12 approximate candidates could support **provisional TCO only**, after the
  separate schema/validation implementation PR and owner approval. None is fully
  TCO-ready; other TCO gates (statutory rules, mass, power, offer fields) were not
  evaluated here.
- The 36 unavailable candidates may retain identity/specification context but must
  be excluded from price-dependent TCO outputs until corrected.
- No candidate in this matrix is `verified` or `derived`.

## 11. Limitations and next actions

Limitations: one bounded research pass; several manufacturer sites blocked or
timed out; no PDF price lists parsed; no EV Database observations; no cross-market
conversion; model-level prices only; no independent verification of registration
statistics cited in the pilot documents.

Next actions (owner decisions):

1. Review and approve the 12 approximate candidates, confirming variants, VAT/NoVA
   basis and exact source text.
2. Manually review BYD's official Austrian price-list PDFs and Tesla's Austrian
   configurator to upgrade the remaining EV gaps.
3. Decide whether to authorize a later EV Database manual observation pass or a
   bounded One Auto API enrichment pass with explicit endpoint rules.
4. Proceed with the separate schema/ingestion implementation PR only after review;
   no staging batch or catalog PR is authorized by this research.

## 12. Safeguards

No `catalog/variants/` write, no staging record, no workflow/CI/gate/secret/provider
change, no scraping, no API key use, no catalog PR and no merge occurred. Every
non-unavailable candidate has `review_required: true`; every unavailable numeric
price field is `null`.
