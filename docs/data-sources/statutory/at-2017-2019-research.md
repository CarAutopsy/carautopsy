# Austrian statutory rate research — 2017–2019 (verified exemption rules)

**Status:** Verified and applied via `docs/data-sources/statutory/at-rules-v1.json`.
All rules are versioned with legal basis, source URL, publisher and retrieval date.
The adapter rejects any record whose registration date falls outside a rule's
verified applicable period; it never interpolates or invents a rate.

## Critical distinction

- **`exemption = true` / `rate = 0`** — a verified legal exemption outcome. This is not a fabricated rate; it is the statutory result for the vehicle class and date.
- **Missing or unverified rate table** — a hard failure. The adapter returns `STATUTORY_RULE_UNAVAILABLE` and rejects the record; no current rule is silently applied.

## Verified sources and applicable periods

### 1. NoVA zero-CO2 electric/hydrogen exemption (M1 BEV)
- Tax: NoVA. Powertrain: `bev`. Qualifying condition: CO2 = 0 g/km.
- Applicable: from 2014-03-01, ongoing (no end date in the cited rule).
- Outcome: `nova_exempt = true`, `nova_rate_eur = 0`.
- Legal basis: § 3 Abs. 1 Z 1 NoVAG 1991. Hybrid vehicles with another fuel source are **not** exempt.
- Source: https://www.bmf.gv.at/themen/steuern/kraftfahrzeuge/normverbrauchsabgabe-uebersicht/nova-befreiung.html
- Publisher: Bundesministerium für Finanzen (BMF); page last updated 2026-01-01; retrieved 2026-11-21. Licence: public statutory publication.

### 2. NoVA M1 non-electric schedule, 2014-03-01 to 2019-12-31
- Outcome: `exemption = false`; formula `(CO2_NEDC − 90) / 5`, cap 32%, +EUR 20/g over 250 g/km, −EUR 300 deduction from 2016.
- Source: https://www.bmf.gv.at/themen/steuern/kraftfahrzeuge/normverbrauchsabgabe-uebersicht/nova-steuersatz/rechtslage_von_1_maerz_2014_bis_31_dezember_2019.html
- Publisher: BMF; page last updated 2026-01-01; retrieved 2026-11-21. Licence: public statutory publication.

### 3. Motor-related insurance tax — BEV exemption through 2025-03-31
- Tax: motorbezogene Versicherungssteuer. Powertrain: `bev`.
- Applicable: historical exemption through **2025-03-31**. From 2025-04-01 electric vehicles are no longer exempt.
- Outcome for 2017–2019 BEVs: `motor_tax_exempt = true`, `motor_tax_rate_eur_per_month = 0`, labelled "verified statutory exemption".
- Legal basis: pre-2025 exemption (§ 4 VersStG 1953); exemption ended by BSMG 2025, BGBl. I Nr. 7/2025, effective 2025-04-01.
- Source: https://www.bmf.gv.at/themen/steuern/kraftfahrzeuge/motorbezogene-versicherungsteuer/befreiungen-motorbezogene-vers/informationen-zur-gratis-vignette.html
- Publisher: BMF; retrieved 2026-11-21. Licence: public statutory publication.

### 4. Motor-related insurance tax — pre-October-2020 non-electric M1 schedule
- Applicable: through **2020-09-30** only.
- Outcome: `exemption = false`; power tiers 0/0.62/0.66/0.75 EUR per kW, minimum EUR 6.20/month (annual payment basis).
- Source: https://www.bmf.gv.at/themen/steuern/kraftfahrzeuge/motorbezogene-versicherungsteuer/steuersatz-motorbezogene-vers.html
- Publisher: BMF; page last updated 2026-01-01; retrieved 2026-11-21. Licence: public statutory publication.

## Canonical 2018 Nissan A02 outcome
- CO2 WLTP = 0 g/km → NoVA exemption applies.
- First registration 2018 → within the BEV motor-tax exemption period → motor-tax exemption applies.
- Price remains unresolved: `purchase_price_excl_vat_eur = null`, `price_pending = true`; no verified bulk Austrian MSRP source was supplied and no price is fabricated.
