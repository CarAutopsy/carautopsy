# Austrian Pilot Batch 001

## Purpose

Define the first bounded 25-model pilot batch for the coverage-first CarAutopsy
pilot.

This document defines scope and acceptance rules only. It does not authorize a
catalog write, staging batch, network retrieval, provider call, workflow change,
CI change, approval-gate change, or secret access.

## Batch objective

Represent 25 high-registration Austrian passenger-car models from model years
2017–2026, beginning with 2025 top sellers, leading brands, and major BEV,
hybrid, and plug-in-hybrid models.

## Model scope

| # | Brand | Model | Priority reason |
|---:|---|---|---|
| 1 | Škoda | Octavia | 2025 Austrian top seller |
| 2 | Volkswagen | Golf | 2025 Austrian top seller |
| 3 | BMW | X1 | 2025 Austrian top seller |
| 4 | Seat | Ibiza | 2025 Austrian top seller |
| 5 | Toyota | Yaris | 2025 Austrian top seller |
| 6 | Dacia | Sandero | 2025 Austrian top seller |
| 7 | Dacia | Duster | 2025 Austrian top seller |
| 8 | Škoda | Fabia | 2025 Austrian top seller |
| 9 | Dacia | Bigster | 2025 Austrian top seller |
| 10 | Volkswagen | Tiguan | High-volume VW SUV |
| 11 | Volkswagen | T-Roc | High-volume VW SUV |
| 12 | Škoda | Kodiaq | High-volume Škoda SUV; existing unresolved price evidence |
| 13 | Škoda | Karoq | High-volume Škoda SUV; existing unresolved price evidence |
| 14 | Audi | A3 | High-volume premium compact |
| 15 | Audi | Q3 | High-volume premium SUV |
| 16 | BMW | 3 Series | High-volume premium sedan |
| 17 | Mercedes-Benz | GLC | High-volume premium SUV |
| 18 | Hyundai | Tucson | High-volume SUV |
| 19 | Kia | Sportage | High-volume SUV |
| 20 | Toyota | Yaris Cross | High-volume hybrid SUV |
| 21 | Toyota | Corolla | High-volume hybrid model |
| 22 | Volkswagen | ID.3 | Leading VW BEV |
| 23 | Škoda | Enyaq | Leading Škoda BEV |
| 24 | Tesla | Model Y | Leading BEV |
| 25 | Volvo | XC40 / EX40 | Leading premium compact BEV |

## Variant selection

For each model, prioritize:

1. The most common Austrian powertrain family.
2. The most common trim or equipment family.
3. The most recent applicable model year within the 2017–2026 scope.
4. A representative body style and transmission where relevant.

Do not attempt to ingest every historical trim in this batch.

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

## Acceptance criteria

A model is considered represented when it has at least one catalog-shaped
pilot record with:

- Resolved identity evidence
- A defined body style and powertrain
- A defined model year
- A price tier and provenance metadata
- A TCO-readiness status of full, provisional, or not ready

## Correction queue

Every approximate, cross-market, range, or unavailable price must remain
tracked for later correction.

A correction requires a dated, attributable source, explicit market and VAT
basis, reviewer approval, and a recorded change reason.

## Execution boundary

This batch plan does not itself create catalog JSON files.

A separate owner-approved implementation PR must add the schema, ingestion, and
validation support required to produce branch-scoped staging records. Only after
that implementation is reviewed may a separate owner-approved batch PR add
records to `catalog/variants/`.
