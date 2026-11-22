# Pilot price-tier and One Auto API workflow

**Status:** implementation support only. No gate is enabled, no catalog record is
written, no staging batch is started, and no live provider call is performed by
this documentation or by the test suite.

## 1. Price tiers

The schema and `scripts/price_tier.py` use exactly six tiers:

| Tier | Minimum evidence |
|---|---|
| `verified` | Exact, dated, attributable Austrian MSRP/list price |
| `derived` | Documented calculation from verified inputs (`derivation_method` required) |
| `approximate` | Dated Austrian MSRP/list-price proxy |
| `approximate_cross_market` | Comparable market price with `source_market`, `fx_date`, `fx_rate`, and `price_adjustment_method` |
| `range` | Positive `price_low` and `price_high` |
| `unavailable` | All price values `null` |

Schema fields: `price_tier`, `price_confidence`, `price_source_date`,
`price_adjustment_method`, `vat_basis`, `review_required`. All are optional in the
structural schema because legacy catalog records predate the pilot; the
price-tier validator enforces the contract where pilot data is used.

## 2. Promotion guard

`price_tier.validate_tier_transition(previous_tier, new_tier)` blocks automated
promotion of `approximate`, `approximate_cross_market`, `range`, or `unavailable`
to `verified`. Promotion requires a new, owner-reviewed correction with an exact
source, market and VAT basis, and a recorded change reason. Downgrades and
same-tier updates are allowed.

The validator also rejects:

- any `price_value`, `price_low`, or `price_high` of `0` (zero is never a placeholder);
- a non-unavailable record without source URL, source date, currency, VAT basis,
  confidence, and `review_required: true`;
- non-positive or non-finite prices;
- `unavailable` records with a non-null price.

## 3. One Auto API adapter

`scripts/oneauto_adapter.py` reads the secret **only** through the environment
abstraction (`ONEAUTOAPI_API_KEY`). The value is never hard-coded, printed,
logged, serialized, committed, or returned in any report. `redact()` removes the
exact secret value, `Bearer` tokens, and key/token/secret assignments from all
rendered text; `safe_error()` classifies exceptions without emitting their bodies.

The source is classified **`enrichment_only`** / **`cross_check_only`** because
`data/sources/registry.json` records `market_scope: ["to_be_verified"]`. One Auto
output can never become verified Austrian pricing.

### Redacted connectivity probe

```bash
python scripts/oneauto_adapter.py --probe
```

- Confirms secret presence without printing the value.
- Performs **at most one** request with a strict timeout.
- Returns a structured, redacted result (status, HTTP code, response hash,
  retrieval date, provider, endpoint, request count).
- Never writes staging or catalog records and never enables a gate.
- With no secret, returns `MISSING_SECRET` and issues zero requests.

### Enrichment fetch

Library callers inject a transport, params, and optional clock/sleeper. A rate
limiter enforces a minimum interval; transient `429`/`5xx` and timeouts use
deterministic exponential backoff. Field whitelisting prevents blind persistence
of provider payloads. Every retained result records provider, endpoint, request
parameters, response timestamp, response hash, source URL, confidence, retrieval
date, and `licence_or_terms: to_be_verified`.

## 4. Branch-scoped pilot staging runner

```bash
python scripts/pilot_staging_runner.py \
  --candidates docs/research/pilot-gap-price-candidates.json \
  --output-dir staging/pilot-batch-001 \
  --report /tmp/pilot-staging-report.json

python scripts/pilot_staging_runner.py \
  --candidates docs/research/pilot-gap-price-candidates.json --dry-run
```

- Reads committed candidate JSON only.
- Validates every candidate; any rejection blocks the whole batch.
- Writes only to a branch-scoped directory under `staging/`; paths under
  `catalog/variants/` are refused with exit code 3.
- Preserves price tier, confidence, VAT basis, source URL/date, adjustment
  method, and `review_required`, and marks each record `staging_only` /
  `catalog_written: false`.
- Reports accepted, rejected, duplicate, conflict, error, and written counts.
- Dry-run writes no files.

## 5. Coverage scoreboard generator

```bash
python scripts/coverage_scoreboard.py \
  --candidates docs/research/pilot-gap-price-candidates.json \
  --weights docs/research/registration-weights-v1.json \
  --report /tmp/coverage-report.json
```

The report includes total models, per-tier counts, registration-weighted
coverage, price-quality coverage, correction-queue count, TCO-ready count, and
coverage gaps. It reads only committed research data and writes no catalog or
staging records.

`docs/research/registration-weights-v1.json` is explicitly a **provisional
priority proxy** built from the 2025 top-seller list, not measured registration
counts. Replace it with an owner-approved Statistik Austria table before using
the weighted figure as an acceptance metric.

## 6. Operator workflow

1. Owner reviews and approves candidate research (separate PR).
2. Run the price-tier validator on any proposed candidate set.
3. Run the staging runner in dry-run mode; inspect counts.
4. Only with owner approval, run a real branch-scoped staging batch.
5. Run the scoreboard generator on committed research data.
6. A separate owner-approved PR is still required before any catalog write.

All gates, live retrieval, provider activation, backlog dispatch, and catalog
ingestion remain paused unless the owner explicitly authorizes them.
