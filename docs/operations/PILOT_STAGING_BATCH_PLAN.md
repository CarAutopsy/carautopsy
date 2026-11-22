# Pilot Batch 001/002 staging batch plan

**Status:** PLAN ONLY. No real staging batch, catalog write, provider call or gate
change is authorized by this document. The first real run requires explicit owner
approval.

## 1. Batch scope

- **Candidate source:** `docs/research/pilot-gap-price-candidates.json` (committed
  research artifact from PR #148).
- **Candidate count:** 48 unique model candidates.
  - Batch 001 contributes 25 models.
  - Batch 002 contributes 24 models; Tesla Model Y appears in both batches and is
    represented once.
- **Price split:** 12 `approximate`, 36 `unavailable`; zero `verified`,
  `derived`, `approximate_cross_market` or `range`.
- **Included:** every candidate in the committed research matrix, because it is
  already an approved research candidate set. The 36 `unavailable` records are
  retained for identity and specification context only and must not participate
  in price-dependent TCO outputs.
- **Excluded:** no model from the matrix is excluded from staging. Models outside
  the matrix are excluded because they have no committed candidate record. The
  five `not_offered_in_austria` candidates and BYD Han remain in the matrix but
  stay `unavailable` pending the decisions in
  `docs/operations/PILOT_EVIDENCE_GAP_PLAN.md`.

## 2. Staging rules

- Use only the branch-scoped directory `staging/pilot-batch-001-002/` on a named
  feature branch. The runner refuses paths outside `staging/` and any path under
  `catalog/variants/`.
- Never write directly to `catalog/variants/`; staging records carry
  `catalog_written: false` and `staging_only: true`.
- Never overwrite or modify an existing catalog record. A future catalog PR is a
  separate, owner-approved action.
- Never silently resolve a conflict. Duplicate keys and conflicting prices are
  counted and reported; a batch with conflicts is rejected. Current detection
  keys include the source URL, so two records for the same vehicle with different
  source URLs and different prices are not yet flagged; identity-level price
  comparison is a documented remaining engineering gap.
- Retain for every record: `price_tier`, `price_value`, `price_source_url`,
  `price_source_date`, `price_confidence`, `price_adjustment_method`, `vat_basis`,
  `currency`, `review_required`, and the original research evidence notes.
- Every `approximate` candidate remains `review_required: true`.
- No `approximate`, `approximate_cross_market`, `range` or `unavailable` candidate
  may be promoted to `verified` by the runner.

## 3. Validation gates

1. **Schema validation** — the record validates against
   `schemas/vehicle-variant.schema.json` (Draft 7).
2. **Price-tier validation** — `scripts/price_tier.validate_price_fields` returns
   no errors for every candidate.
3. **Provenance validation** — non-unavailable records have source URL, source
   date, currency, VAT basis, confidence and `review_required: true`.
4. **Duplicate detection** — no duplicate brand/model/variant/year/source
   combination.
5. **Zero-placeholder rejection** — no `price_value`, `price_low` or `price_high`
   equals `0`.
6. **Promotion guard** — no forbidden tier is promoted to `verified`.
7. **Catalog-conflict check** — compare staged identities against existing
   `catalog/variants/` records read-only. This check is **not yet implemented**
   and is listed in the engineering gap plan.
8. **Staging-report review** — owner reviews accepted, rejected, duplicate,
   conflict and error counts before any catalog step.

## 4. Expected outcome

For the default all-candidate run:

| Metric | Expected |
|---|---:|
| Accepted | 48 |
| Rejected | 0 |
| Duplicates | 0 |
| Conflicts | 0 |
| Errors | 0 |
| Written staging records | 48 |
| Catalog writes | 0 |
| Catalog records now and after staging | 120 |
| Catalog records after a future approved catalog PR | 120 unchanged until the owner explicitly approves catalog ingestion |

An owner may narrow the first batch to the 12 `approximate` candidates; in that
case expected accepted/written counts are 12 and the 36 unavailable records stay
in research only. Either choice must be recorded in the owner approval.

## 5. Rollback plan

- Delete the branch-scoped staging directory `staging/pilot-batch-001-002/`.
- Do not touch `catalog/variants/`; there is nothing to revert there.
- Do not revert `main` or rewrite merged history.
- Do not delete research evidence, the candidate matrix or the scoreboard data.
- Do not disable or alter any gate, workflow, CI, secret or provider setting.

## 6. Owner approval checklist

- [ ] Dry-run report reviewed and accepted.
- [ ] Staging report reviewed (accepted/rejected/duplicate/conflict/error counts).
- [ ] Catalog-conflict report reviewed once implemented.
- [ ] Approximate-price provenance reviewed for all 12 candidates.
- [ ] VAT basis reviewed (`incl_vat`, 20% Austrian VAT where documented).
- [ ] Source dates reviewed, including the archived 2018/2019 Škoda evidence.
- [ ] Cross-market adjustments reviewed (none present in this batch).
- [ ] Owner explicitly authorizes creation of a catalog PR, if any.
