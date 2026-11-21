# Austrian statutory rate research — 2017–2019 (RESEARCH ONLY, NOT APPLIED)

**Status:** Incomplete. Two of three required rate tables were found on official BMF pages; the 2017–2019 **BEV motor-tax** table was not found. Per owner instruction, nothing here has been written into the AT country pack and no fabricated rate is used. The statutory gate remains 0/154.

## Verified sources and extracted rules

### 1. NoVA, 1 March 2014 – 31 December 2019 (covers 2017–2019)
- Source: Bundesministerium für Finanzen (BMF), "Rechtslage von dem 1. März 2014 bis 31. Dezember 2019"
- URL: https://www.bmf.gv.at/themen/steuern/kraftfahrzeuge/normverbrauchsabgabe-uebersicht/nova-steuersatz/rechtslage_von_1_maerz_2014_bis_31_dezember_2019.html
- Page last updated: 2026-01-01. Licence: public statutory publication.
- M1 passenger cars: rate = `(CO2_g_per_km[NEDC] - 90) / 5`, commercially rounded, capped at 32%.
- CO2 malus: +EUR 20 per g/km above 250 g/km.
- Abzugsposten from 2016: EUR 300 for all passenger cars.
- BEV / hydrogen (CO2 = 0 g/km) exempt under §3 Abs 1 Z 1 NoVAG 1991 — source: https://www.bmf.gv.at/themen/steuern/kraftfahrzeuge/normverbrauchsabgabe-uebersicht/nova-befreiung.html (last updated 2026-01-01).

### 2. Motorbezogene Versicherungssteuer, M1 first registered before 1 October 2020 (covers 2017–2019) — non-electric only
- Source: BMF "Steuersatz" page
- URL: https://www.bmf.gv.at/themen/steuern/kraftfahrzeuge/motorbezogene-versicherungsteuer/steuersatz-motorbezogene-vers.html
- Page last updated: 2026-01-01. Licence: public statutory publication.
- Annual premium payment: first 24 kW EUR 0; next 66 kW EUR 0.62/kW; next 20 kW EUR 0.66/kW; beyond EUR 0.75/kW; minimum EUR 6.20/month.

### 3. BEV M1 motor tax, 2017–2019 — NOT FOUND
- The current BMF page documents a BEV formula (45 kW deduction, 900 kg deduction, tiered power/weight rates) but does not establish that it applied to 2017–2019 registrations. The engine's readiness gate requires a `motorbezogene_versicherungssteuer.bev_m1` schedule for BEVs.
- Searches of BMF pages and public search results did not surface a dated 2017–2019 BEV rate table.
- **No value is assumed or fabricated.** This is the blocking gap.

## Consequence
- No statutory rates were added to `country-packs/AT/`.
- The `--no-taxes` structural gate (9 passes) is unchanged.
- Owner action needed: provide a verified 2017–2019 BEV motor-tax table (official BMF/BMK publication or curated attributed dataset) before statutory acceptance can be attempted.

## Price source
No reliable bulk Austrian MSRP dataset (OEM dump, mobile.de/autoscout24 aggregate) was available in this environment. The canonical proposal keeps `purchase_price_excl_vat_eur: null` and `price_pending: true`. No price is fabricated.
