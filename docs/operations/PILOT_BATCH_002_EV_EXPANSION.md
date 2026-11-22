# Austrian EV Expansion Batch 002

## Purpose

Expand the CarAutopsy Austrian coverage pilot to all current Tesla, XPeng, and
BYD passenger-car models available or recently offered in Austria.

This batch prioritizes battery-electric vehicles and ensures that the pilot does
not underrepresent newer Chinese and American EV brands simply because
Austrian-specific verified price evidence is incomplete.

This document defines research and coverage scope only. It does not authorize a
catalog write, staging batch, network retrieval, provider call, workflow change,
CI change, approval-gate change, or secret access.

## Coverage rule

Cover every Tesla, XPeng, and BYD passenger-car model with an Austrian market
presence or a credible recent Austrian offering.

For each model, prioritize:

1. The current Austrian-market configuration.
2. The most common powertrain and drivetrain configuration.
3. The most recent applicable model year.
4. A representative trim or equipment family.
5. A credible Austrian or comparable EU/EEA price proxy where exact Austrian
   evidence is unavailable.

## Tesla scope

| Brand | Model | Priority |
|---|---|---|
| Tesla | Model 3 | High — core Austrian BEV sedan |
| Tesla | Model Y | High — leading Austrian BEV SUV |
| Tesla | Model S | Medium — premium flagship sedan |
| Tesla | Model X | Medium — premium flagship SUV |
| Tesla | Cybertruck | Research only; include only if an Austrian-market offering or credible EU import pathway is documented |

Tesla Austria lists Model 3, Model S, Model X, and Model Y in its current
Austrian inventory and product pages.

## XPeng scope

| Brand | Model | Priority |
|---|---|---|
| XPeng | G6 | High — current Austrian SUV coupé |
| XPeng | G9 | High — current Austrian electric SUV |
| XPeng | P7+ | High — current Austrian fastback sedan |
| XPeng | L03 | High — current Austrian SUV coupé |
| XPeng | X9 | Medium — premium electric MPV |
| XPeng | G9L | Research and include when an Austrian offering is documented |
| XPeng | L05 | Research and include when an Austrian offering is documented |

XPeng Austria currently presents G6, G9, P7+, L03, and X9, with Austrian
leasing offers and Austrian-market product information.

## BYD scope

| Brand | Model | Priority |
|---|---|---|
| BYD | Dolphin | High — compact BEV hatchback |
| BYD | Dolphin Surf | High — compact BEV hatchback |
| BYD | Atto 3 | High — compact BEV SUV |
| BYD | Seal | High — BEV sedan |
| BYD | Seal U | High — BEV SUV |
| BYD | Seal U DM-i | High — plug-in hybrid SUV |
| BYD | Tang | Medium — seven-seat BEV SUV |
| BYD | Han | Medium — premium BEV sedan |
| BYD | Sealion 7 | High — BEV SUV coupé |
| BYD | Sealion 8 | Research and include when an Austrian offering is documented |
| BYD | eMAX 7 | Medium — electric MPV |
| BYD | M3 | Research and include when an Austrian offering is documented |

Include only passenger-car models. Commercial vans, buses, trucks, and
non-passenger vehicles are out of scope for this batch.

## Price acceptance

Apply the resolution order in
`docs/data-sources/approximate-price-protocol-v1.md`.

A record may be prepared with:

- `verified`
- `derived`
- `approximate`
- `approximate_cross_market`
- `range`

A record with `price_unavailable` may retain identity and specification
information but must not participate in price-dependent TCO outputs.

## BEV-specific fields

For every BEV record, capture where evidence permits:

- Battery capacity, gross and usable where distinguishable
- WLTP combined range
- DC charging power and 10–80% charging time where documented
- drivetrain: FWD, RWD, or AWD
- motor count and power
- seating capacity
- body style
- charging connector standard
- Austrian price tier and provenance

Never infer a battery capacity, range, charging speed, price, or trim from
another variant.

## Research deliverables

Create:

- `docs/research/tesla-xpeng-byd-austria-price-research.md`
- `docs/research/tesla-xpeng-byd-austria-price-candidates.json`

For every model, record:

- Austrian market status
- Current or most recent Austrian model year
- Powertrain and drivetrain
- Body style and seating capacity
- Candidate price tier
- Candidate price or range
- Source URL and source date
- Currency and VAT basis
- Confidence level
- Adjustment method for cross-market evidence
- Evidence gaps
- Recommended next action

## Correction queue

Every approximate, cross-market, range, or unavailable price must remain
tracked for later correction.

A correction requires a dated, attributable source, explicit market and VAT
basis, reviewer approval, and a recorded change reason.

## Execution boundary

This batch plan does not create catalog JSON files.

A separate owner-approved implementation PR must add schema, ingestion, and
validation support for branch-scoped staging records. Only after that
implementation is reviewed may a separate owner-approved batch PR add records
to `catalog/variants/`.
