# Approximate Price Protocol v1

## Purpose

This protocol enables a coverage-first CarAutopsy pilot for Austrian passenger
vehicles from model years 2017–2026.

Its objective is practical market coverage, not perfect evidence coverage.
Where a verified Austrian price is unavailable, the project may record a clearly
labeled best-available MSRP or list-price proxy. Approximate values must remain
distinguishable from verified values and must be correctable later.

## Core principle

No price, specification, VIN, identity field, or other factual attribute may be
invented.

An approximate price is an explicitly labeled estimate based on a documented
source. It is not a verified Austrian transaction price and must not silently
become one.

## Price tiers

| Tier | Meaning | Permitted use | Required metadata |
|---|---|---|---|
| `verified` | Exact, dated, attributable Austrian price evidence | Full TCO eligibility | Source URL, source date, market, VAT basis |
| `derived` | Calculated from verified inputs using an approved rule | TCO eligible with caveat | Formula, inputs, derivation date |
| `approximate` | Best available Austrian MSRP/list-price proxy | Pilot analysis; provisional TCO | Source URL, retrieval date, confidence, adjustment basis |
| `approximate_cross_market` | Comparable EU/EEA price converted or adjusted for Austria | Pilot analysis only | Source market, FX rate/date, adjustment method, confidence |
| `range` | Credible low/high price range only | Pilot analysis only | Low, high, midpoint estimate, source basis |
| `unavailable` | No defensible price proxy | Exclude from price-dependent outputs | Reason and revisit date |

## Resolution order

For every candidate vehicle variant, apply this order:

1. Resolve an exact verified Austrian price from committed evidence.
2. If unavailable, resolve an Austrian manufacturer MSRP, official configurator
   price, or dated reputable Austrian automotive price source.
3. If unavailable, resolve a comparable EU/EEA market price and apply a
   documented conversion or adjustment.
4. If only a credible range is available, record the range and a provisional
   midpoint.
5. If no defensible proxy exists, mark the record `price_unavailable`; retain
   all available identity and specification evidence.

## Required fields

Every non-`unavailable` approximate record must include:

- `price_tier`
- `price_value` or `price_low` / `price_high`
- `currency`
- `price_basis`, such as MSRP, list price, or configurator price
- `price_source_url`
- `price_source_date`
- `price_confidence`
- `adjustment_method`, when conversion or adjustment is applied
- `vat_basis`
- `review_required: true`

## Confidence levels

| Level | Meaning |
|---|---|
| `high` | Current Austrian manufacturer or official dealer-configurator price |
| `medium` | Dated reputable Austrian price source or recent comparable-market price |
| `low` | Older, indirect, or cross-market proxy; use only for pilot coverage |

## TCO policy

- `verified` and `derived` records may be treated as TCO-ready when all other
  TCO gates pass.
- `approximate`, `approximate_cross_market`, and `range` records may support
  provisional TCO only.
- Provisional TCO output must display the price tier and a clear uncertainty
  notice.
- Approximate values must not be promoted to `verified` without new evidence
  and an owner-approved correction pass.

## Correction path

Each approximate record must remain visible in the correction queue until it is
upgraded, replaced, or explicitly retired.

A correction requires:

- A dated, attributable source
- An explicit market and VAT basis
- A reviewer-approved evidence upgrade
- A recorded change reason

## Safeguards

- No network access is authorized by this protocol.
- No secret, API key, paid provider, or live retrieval is introduced.
- No workflow, CI, approval gate, or catalog-write gate is changed by this
  documentation.
- Approximate records remain clearly separated from verified records.
- The pilot accepts 95% practical coverage as preferable to excluding otherwise
  useful vehicles solely because a verified price is unavailable.
