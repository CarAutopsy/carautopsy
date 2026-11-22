# Austria Priority Coverage Backlog

## Pilot scope

This backlog prioritizes Austrian passenger vehicles from model years
2017–2026 for the coverage-first CarAutopsy pilot.

The objective is to represent the vehicles with the greatest practical Austrian
market relevance, rather than to catalog every historical trim before providing
usable coverage.

## Priority order

1. 2025 Austrian top-selling models.
2. Current or recent models from the top 10 Austrian brands.
3. Leading BEV, hybrid, and plug-in hybrid models.
4. High-volume fleet and private-market models from 2017–2026.
5. Lower-volume or discontinued models only after the priority backlog is
   substantially covered.

## Initial brand priorities

Prioritize representation for:

- Volkswagen
- Škoda
- BMW
- Audi
- Dacia
- Mercedes-Benz
- Hyundai
- Seat
- Toyota
- Cupra

## Initial model priorities

Prioritize at least the following 2025 Austrian top sellers:

- Škoda Octavia
- Volkswagen Golf
- BMW X1
- Seat Ibiza
- Toyota Yaris
- Dacia Sandero
- Dacia Duster
- Škoda Fabia
- Dacia Bigster

Also prioritize major BEV and hybrid models from Volkswagen, Škoda, BMW, Audi,
Mercedes-Benz, Hyundai, Kia, Toyota, Volvo, Tesla, and other high-registration
brands.

## Price acceptance

Use the resolution order in
`docs/data-sources/approximate-price-protocol-v1.md`.

A record may enter the pilot catalog with:

- `verified` price evidence
- `derived` price evidence
- `approximate` Austrian MSRP/list-price proxy
- `approximate_cross_market` comparable-market proxy
- `range` where only a credible low/high range is available

A record with `price_unavailable` may still retain identity and specification
evidence, but must not participate in price-dependent TCO outputs.

## Pilot batch

The first pilot batch should target no more than 25 high-registration models.
For each model, prioritize the most common Austrian powertrain and trim
families before expanding to secondary variants.

## Correction queue

Every approximate, cross-market, range, or unavailable price must remain
tracked for later correction.

A correction requires a dated, attributable source, an explicit market and VAT
basis, reviewer approval, and a recorded change reason.

## Safeguards

This backlog does not authorize catalog writes, network retrieval, provider
calls, workflow changes, CI changes, approval-gate changes, or secret access.
A separate owner-approved batch PR is required before any record enters
`catalog/variants/`.
