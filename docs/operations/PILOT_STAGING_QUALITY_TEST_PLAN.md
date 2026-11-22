# Pilot staging quality test plan

**Status:** test specification for the catalog-conflict and identity-resolution
work in PR #156. This document defines tests and expected behavior; it does not
implement them or run a staging batch.

Fixtures live in `tests/fixtures/pilot_staging_quality/` and are fully synthetic.

## 1. Identity canonicalization

Normalize identity as `make | model | variant | model_year`, with these rules:

| Test case | Fixture input | Expected result |
|---|---|---|
| Case normalization | `fixturebrand` / `FixtureBrand` | Same canonical make |
| Whitespace normalization | ` FixtureModel ` / `FixtureModel` | Same canonical model |
| Trim normalization | `FixtureTrim` vs equivalent trim alias | Same canonical variant unless trim is a real differentiator |
| Model-year handling | 2023 vs 2024 | Different identity; report as model-year variant, not an exact duplicate |
| Body-style handling | hatchback vs sedan | Different identity; never merged |
| Powertrain handling | petrol vs diesel | Different identity; never merged |
| Drivetrain handling | FWD vs AWD | Different identity; never merged |

Use `catalog_quality.normalize_identity` conventions wherever available. Never
collapse distinct trims, years, body styles, powertrains or drivetrains silently.

## 2. Catalog-conflict detection

Source: `catalog_existing_records.json` (24 synthetic existing records).

| Test case | Expected result |
|---|---|
| Exact identity match | Conflict; batch blocked |
| Near-identity match (model 0 variants) | Reported as near-duplicate for owner review |
| Conflicting price for same identity | Conflict with both prices recorded; never auto-resolve |
| Conflicting source date | Reported; requires owner review |
| Conflicting VAT basis | Reported; requires owner review |
| Conflicting provenance | Reported; no promotion to verified |

The catalog directory is read-only for the detector; no record may be overwritten.

## 3. Within-batch duplicate detection

Source: `staging_candidates_duplicate_identity.json` (12 records).

| Test case | Expected result |
|---|---|
| Exact duplicate | One kept; duplicate counted |
| Case-insensitive duplicate | Duplicate counted |
| Whitespace-insensitive duplicate | Duplicate counted |
| Trim-level duplicate | Reported as trim variant, not silently dropped |
| Model-year duplicate | Reported as year variant |
| Conflicting price for same identity | Conflict counted; batch blocked |

The current runner's deduplication key includes the source URL; test must document
that two records for the same vehicle with different source URLs and different
prices are **not yet** detected as a conflict (engineering gap).

## 4. Price-tier validation

Sources: `staging_candidates_valid.json` (24 records),
`staging_candidates_promotion_violations.json` (12 records).

| Test case | Expected result |
|---|---|
| Verified with exact dated Austrian evidence | Accepted |
| Approximate cannot promote to verified | Rejected by promotion guard |
| Cross-market cannot promote to verified | Rejected by promotion guard |
| Range cannot promote to verified | Rejected by promotion guard |
| Unavailable must have null price fields | Non-null price rejected |
| No zero placeholders | Any `price_value`/`price_low`/`price_high == 0` rejected |
| All six tiers represented | Verified, derived, approximate, approximate_cross_market, range, unavailable |
| Cross-market requires FX metadata | Market, currency, FX date/rate and adjustment method required |
| Derived requires documented method | Rejected without derivation method |

## 5. Provenance validation

Source: `staging_candidates_invalid_provenance.json` (12 records).

Each record omits exactly one required field. Expected result: rejection naming the
missing field.

| Required field | Test case |
|---|---|
| Source URL | Missing `price_source_url` → reject |
| Source date | Missing `price_source_date` → reject |
| Currency | Missing `currency` → reject |
| VAT basis | Missing `vat_basis` → reject |
| Confidence | Missing `price_confidence` → reject |
| Review flag | Missing or false `review_required` → reject |

All non-unavailable records must retain `review_required: true`.

## 6. Staging report

For both dry-run and real staging modes, assert:

| Metric | Expected |
|---|---|
| Accepted count | Matches valid fixture count |
| Rejected count | Matches invalid fixture count |
| Duplicate count | Matches duplicate fixture count |
| Conflict count | Matches conflict fixture count |
| Error count | Matches error fixture count |
| `catalog_variants_written` | Always 0 |
| `provider_calls` | Always 0 |
| `written` | 0 in dry-run; equals accepted in real branch-scoped run |

The catalog must remain at 120 records in every test, and no staging directory
may be created by dry-run tests.

## 7. Test execution boundaries

- No real secrets, tokens, cookies or credentials in fixtures or tests.
- No network calls, provider calls or live retrieval.
- No catalog writes and no staging records outside a branch-scoped directory.
- Synthetic prices are fixture data only and are never presented as real evidence.
