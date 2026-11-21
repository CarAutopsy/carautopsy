# Identity-resolution plan — EEA type-approval identity to consumer-facing identity

**Status:** Research only. No catalog write, no retrieval/paid-provider activation, no gate change.
**Date:** 2026-11-21.
**Scope:** 100-1,000 Austrian/EU variants, starting from the committed 154-row 2018 WLTP sample at
`docs/data-sources/sample/eea_at_2018_wltp_sample.tsv`.
**Problem evidence (measured, not assumed):** all 154 sampled rows have `make == model`
(145 x SKODA/SKODA, 9 x NISSAN/NISSAN) and 57 distinct `variant` values, almost all long
type-approval codes (e.g. `NFD7FD7CW0027CPSTVLN1C7B`) plus the short code `A02`. EEA supplies no
consumer-facing model, trim or generation. The current rule therefore marks all 9 passing
proposals `identity_quality = "requires_manual_curation"`. Resolving this *without invention* is
the purpose of this plan.

## 1. Candidate comparison

### A. Manual curation workflow for low-volume, high-value records
- **Source URL:** internal process; see `docs/data-sources/step3-owner-checkpoint.md` and this file.
- **License / attribution:** project-owned work product; cite the EEA source (CC BY 4.0) for the
  technical facts being annotated, plus whichever documentation is used for the consumer identity.
- **Coverage:** unlimited in principle, but human-bound; realistic throughput is a few dozen records
  per review session at documented quality.
- **Fields:** can supply `make`, `model`, `trim`, `generation`, `market`, `model_year` with an
  evidence note for each.
- **Update cadence:** on demand, per batch; no automatic refresh.
- **Cost:** human reviewer time; no licence fee.
- **Suitability for Austrian/EU vehicles:** **high** — a curator can read Austrian/OEM documentation
  and is the only option that can honestly resolve the 2017-2019 Nissan/Skoda codes from evidence.
- **Risk:** slow; inconsistent if evidence standard is not fixed (the field contract in section 4
  fixes it).

### B. Public vehicle-identity database / API with an explicit licence
- **Source URL:** Wikidata + SPARQL endpoint `https://query.wikidata.org/`
  (data licence: CC0 1.0 for the database dump; confirm the current licence notice before reuse);
  NHTSA vPIC `https://vpic.nhtsa.dot.gov/api/` (US government service; exact bulk-reuse terms must be
  verified by the owner before any use).
- **License:** Wikidata database content is published under an explicit open licence (CC0 1.0 at the
  time of writing, previously CC BY-SA); vPIC is a free US-government API but its bulk reuse terms
  are not documented as an open data licence and must be verified.
- **Coverage:** good for mass-market make/model/generation and some trims; **poor at type-approval
  code level**; vPIC is US-market/VIN-centric and has little Austrian/EU coverage.
- **Fields:** make, model, generation, sometimes trim and production years; **no Austrian market
  trim**, no reliable mapping from an EEA `Ve`/`Va` code.
- **Update cadence:** community/government driven, irregular; no SLA.
- **Cost:** free at point of use; engineering cost for a matcher and an attribution record.
- **Suitability for Austrian/EU vehicles:** **low to medium**. Useful as a *cross-check* for a
  consumer model name once a code has been resolved by other evidence; not usable as the primary
  resolver for these 154 records because no code-to-identity mapping exists in these sources.
- **Risk:** a fuzzy name match could silently invent an identity. The matcher must be evidence-only:
  a candidate is accepted only if an explicit source URL and licence are stored with the record.

### C. Curated mapping table derived from OEM/model documentation
- **Source URL:** versioned file in this repository, e.g.
  `docs/data-sources/identity-map/v1.json`; evidence URLs point to OEM model archives, type-approval
  sheets or national road-authority documentation (e.g. OEM press/portal pages and EEA record pages).
- **License:** project-owned table; each row carries the upstream source URL and its licence/terms.
  OEM pages are generally proprietary — link and quote the minimum necessary, never bulk-copy.
- **Coverage:** exactly the variants a curator has documented; grows linearly with review effort.
- **Fields:** keyed by `(make, model, variant, powertrain, model_year, market)` with resolved
  `consumer_make`, `consumer_model`, `trim`, `generation`, plus provenance and confidence.
- **Update cadence:** versioned with the table; reviewed per batch.
- **Cost:** curator time + small maintenance cost; no licence fee.
- **Suitability for Austrian/EU vehicles:** **high** — this is the only machine-checkable form that
  preserves evidence for Austrian type-approval codes.
- **Risk:** stale entries; mitigated by `retrieved_at` and per-entry `source_url`.

## 2. Recommendation

**Recommended approach for the first 100-1,000 variants: C (curated mapping table) as the system of
record, with A (manual curation) as the process that fills it. B (public database/API) is an optional
cross-check only.**

Rationale: the binding constraint is not volume, it is *evidence*. Every one of the 154 sampled
records has an unresolved type-approval identity; no open database maps those codes to a consumer
identity. A curated table lets each resolution be reviewed, attributed and reproduced, and scales
linearly to the target range without fabricating names. The public API is deliberately not primary:
its coverage of 2017-2019 Austrian type-approval codes is unproven, and an unverified fuzzy match
would violate the no-invention rule.

Expected coverage: **0 of 154 today** (no mapping rows exist yet). After a curation pass, expected
coverage is proportional to documented rows; the target is >=95% of the *deduplicated* candidate set
(57 distinct variant codes in this sample, 9 of them the Nissan A02 group), not 154 raw registrations.
No coverage is claimed until the mapping file exists and the reporting script in
`scripts/report_research_coverage.py` measures it.

## 3. How to resolve EEA fields without inventing data

1. **Build the match key** from EEA fields exactly as stored in `source_fields`:
   `make` (`Mh`/`Man`), `model` (`Mk`/`MMS`), `variant` (`Ve`/`Va`/`T`), `powertrain` (`Ft`),
   `model_year` (registration year) and `market` (`MS`). These are technical facts and are never
   rewritten.
2. **Look up the key in the versioned mapping table.** An exact key match is required; no fuzzy or
   "closest name" matching. If no exact row exists, stop — the record stays
   `requires_manual_curation`.
3. **Validate the mapping row** has a `source_url`, `license`, `retrieved_at`, and a human reviewer
   (`reviewed_by`). A row without all four is not evidence.
4. **Copy the resolved values** (`consumer_make`, `consumer_model`, `trim`, `generation`) into
   `identity`. The consumer trim also replaces the raw `identity.variant_name` approval code for
   display; the original EEA strings remain untouched in `source_fields` for audit.
5. **Optionally cross-check** the consumer model against a public database (candidate B). A
   disagreement is a finding, not an overwrite; the curator resolves it.
6. **Mark `identity_resolved` only** when section 4's contract is satisfied. Never derive a model
   name from the make, never expand an approval code by pattern, never guess a trim from power.

For the canonical Nissan row: EEA gives `make=NISSAN`, `model=NISSAN`, `variant=A02`,
`powertrain=bev`, `model_year=2018`, `market=AT`. There is no mapping row and no documented
consumer model/trim/generation in the proposal, so it correctly remains
`requires_manual_curation`. No Nissan model or trim name is asserted here.

## 4. Exact contract for `identity_resolved`

A proposal may be marked `identity_quality = "identity_resolved"` only when **all** of the following
are present and non-empty in the proposal:

| Field | Requirement |
|---|---|
| `identity.make` | consumer-facing make; non-empty; must not equal `identity.model` |
| `identity.model` | consumer-facing model; non-empty; must not equal `identity.make` |
| `identity.trim` | consumer-facing trim/market name; must not be a type-approval code |
| `identity.generation` | documented generation label (or generation-equivalent model code with an evidence URL) |
| `identity.model_year` | integer model year matching `registration.first_registration_date` year |
| `identity.market` | exact market code, e.g. `AT` |
| `identity.resolution.method` | `curated_mapping` (public-DB cross-check recorded separately) |
| `identity.resolution.source_url` | evidence URL for the consumer identity; must be an http(s) URL |
| `identity.resolution.license` | licence/terms of that evidence |
| `identity.resolution.retrieved_at` | ISO date the evidence was retrieved |
| `identity.resolution.matched_fields` | the exact EEA key fields used for the lookup |
| `identity.resolution.reviewed_by` | human reviewer identifier |
| `curation_reason` | `null` (no outstanding curation question) |

`source_fields`, `provenance`, `statutory` and technical facts remain byte-for-byte unchanged by
resolution. Any failure of this contract keeps `identity_quality = "requires_manual_curation"` and
is reported with an explicit reason. The reporting script treats missing mapping data as **0
resolved**, never as an assumed pass.

## 5. Owner decisions required before any ingestion

1. Approve the curated-table format and the per-entry evidence standard in section 4.
2. Assign a reviewer for the first batch (57 distinct codes in this sample).
3. Confirm that no identity is ingested while `identity_quality != "identity_resolved"`.
