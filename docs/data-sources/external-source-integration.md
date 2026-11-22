# External Source Integration Policy

## Purpose

Define how CarAutopsy may use external automotive-data sources during the
Austrian coverage-first pilot.

This policy applies to One Auto API and EV Database. It separates API-based
enrichment from web-reference research and prevents either source from silently
becoming verified Austrian price evidence.

## Source roles

| Source | Access mode | Primary use | Price-tier ceiling |
|---|---|---|---|
| One Auto API | Secret-backed API | Vehicle-data enrichment, cross-checking, and provider aggregation where its terms and market coverage permit | Source-dependent; never automatically verified for Austria |
| EV Database | Web reference portal | European BEV specifications, range, battery, charging, body style, weight, and European price candidates | `approximate` or `range` |
| Austrian manufacturer/dealer source | Web reference or official document | Austrian MSRP, configurator price, and market-specific evidence | `verified` or `approximate` |
| EEA regulatory evidence | Committed dataset | Identity, specifications, and regulatory context | Not a price source |

## One Auto API

One Auto API is authorized as a secret-backed enrichment source.

The API key must be stored only as the GitHub Actions secret:

```text
ONEAUTOAPI_API_KEY
```

Rules:

- Never commit, print, log, or expose the key value.
- Read the key only through `secrets.ONEAUTOAPI_API_KEY`.
- Do not place the key in source files, tests, reports, PR bodies, issues, or
  command output.
- Redact all credentials, tokens, and request headers from stored evidence.
- Use bounded, purpose-limited requests; no unattended bulk harvesting.
- Record the endpoint, request parameters, response hash, retrieval date, and
  licence/terms for every retained result.
- Treat One Auto API as enrichment and cross-check data unless its documented
  terms and market coverage explicitly support Austrian price evidence.

## EV Database

EV Database has no authorized public API in this pilot. Use its web portal as a
manual research reference.

Rules:

- Record the exact vehicle URL, retrieval date, and displayed price or range.
- Capture battery capacity, WLTP range, efficiency, DC charging, body style,
  weight, drivetrain, and other available specifications only when directly
  displayed.
- Do not scrape, automate, or bypass the portal.
- Do not treat a European price as an Austrian MSRP.
- Classify EV Database price evidence as `approximate` or `range`, never
  `verified`.
- Use Austrian manufacturer, dealer, or official Austrian automotive sources to
  upgrade a record to Austrian-specific evidence.

## Price-tier rules

| Evidence | Permitted tier |
|---|---|
| Exact, dated, attributable Austrian MSRP/list price | `verified` |
| Calculation from verified inputs using an approved rule | `derived` |
| Dated Austrian MSRP/list-price proxy | `approximate` |
| EV Database European price candidate | `approximate` or `range` |
| One Auto API price candidate, if permitted by its terms | Source-dependent; default `approximate` or `range` |
| No defensible price evidence | `unavailable` |

## Required provenance

Every externally sourced field must retain:

- `source_id`
- `source_url`
- `retrieval_date`
- `licence_or_terms`
- `market`
- `currency`, when applicable
- `vat_basis`, when applicable
- `confidence`
- `price_tier`, when applicable
- `adjustment_method`, when conversion or adjustment is applied
- `review_required`

## Safeguards

- No catalog write is authorized by this policy.
- No staging batch is authorized by this policy.
- No workflow, CI, approval-gate, or secret-value change is authorized by this
  policy.
- No automated scraping of EV Database is permitted.
- No secret value may enter the repository, logs, reports, or pull requests.
- A separate owner-approved implementation PR is required before API adapters,
  ingestion paths, or catalog writes are added.
