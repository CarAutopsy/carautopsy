# Identity conflict resolution tool

**Status:** tool implementation and synthetic tests only (PR #156). It has not
been run against the local 48-record staging batch and must not be used to
promote, merge, overwrite, delete or write any record.

## CLI

```bash
# validate only; writes nothing
python scripts/identity_conflicts.py \
  --check --candidates tests/fixtures/identity_conflicts/exact_duplicate.json

# emit a deterministic report under docs/research or docs/operations
python scripts/identity_conflicts.py \
  --candidates tests/fixtures/identity_conflicts/exact_duplicate.json \
  --catalog tests/fixtures/identity_conflicts/catalog_snapshot.json \
  --report docs/research/identity-conflict-report.json
```

Exit codes: `0` success/check, `2` CLI error, `3` validation or unsafe-path error.
Report paths under `catalog/`, `catalog/variants/` and `staging/` are refused;
only `docs/research/` and `docs/operations/` are allowed. The real staging batch
and live catalog are also refused as **input** paths.

## Normalization

Only fields with repository-defined canonical forms are normalized, using
`catalog_quality.normalize_identity` and `slugify`: make, model, generation,
variant slug and model year. Powertrain is casefolded by that helper. Every
normalized value is accompanied by its original raw value in the report's
`candidate_identity`; body style, trim, battery capacity, range, dimensions,
weight, price and provenance are compared as supplied, never silently changed.

## Conflict classes

| Class | Meaning |
|---|---|
| `exact_duplicate` | Same canonical identity and no differing watched field, or same identity as an existing catalog record |
| `probable_duplicate_owner_review` | Same canonical identity but raw make/model differs by case or whitespace |
| `conflicting_attribute` | Same identity with different model year, body style, powertrain, trim, battery, range, dimensions, weight, price evidence or provenance |
| `missing_mandatory_identity_field` | Make or model is absent |
| `unsupported_identity_assertion` | Identity field has an unsupported type |
| `unresolved_variant` | Variant identifier is absent or ambiguous |

Kodiaq/Karoq-style unresolved variants are represented only by synthetic
`FixtureBrand` fixtures. The real Kodiaq/Karoq identity evidence and exhaustive
search audit trail are not touched by this tool.

## Report schema

The report carries `schema_version`, `artifact`, `deterministic`, `input_files`
(path, SHA-256, `read_only: true`), counts and zero counters for `catalog_writes`,
`staging_writes`, `provider_calls`, `records_merged`, `records_overwritten`,
`records_deleted` and `records_promoted`.

Each finding contains:

- `candidate_identity` — variant id and raw make/model/variant/year;
- `conflicting_field` — watched field or identity component;
- `competing_values` — all differing values;
- `source_provenance` — one provenance reference per competing value;
- `recommended_resolution` — one of the six conflict classes;
- `owner_decision_required` — boolean;
- `action` — suggested owner action.

Output is deterministic: sorted keys, stable finding order and no timestamps.

## Summary counts

The report includes a `summary` object with these counts and rules:

| Count | Rule |
|---|---|
| `accepted` | Candidate variant ids not referenced by any finding |
| `rejected` | Distinct candidates with `missing_mandatory_identity_field`, `unsupported_identity_assertion` or `unresolved_variant` |
| `duplicate` | Distinct candidates with `exact_duplicate` or `probable_duplicate_owner_review` |
| `conflict` | Distinct candidates with `conflicting_attribute` |
| `error` | `unverified_approximate_claim` guard findings |

Counts are **not mutually exclusive**: one candidate can be both duplicate and
conflict. Every finding stays visible in `findings`.

Group comparison compares every record against the first record in the group.
A `probable_duplicate_owner_review` finding is emitted when raw make/model casing
or whitespace differs, but it does **not** stop attribute comparison; differing
model year, battery capacity, price evidence and other watched fields are still
reported as `conflicting_attribute` findings.

## Verified-claim guard

A candidate whose `price.price_tier` is `verified` while its supporting evidence
is approximate (`evidence_tier: approximate`, `approximate: true`, or a proxy
`source_type`) produces an `unverified_approximate_claim` finding. The record is
reported only; the tool never changes, promotes, or writes it.

## Mutation counters

`catalog_writes`, `staging_writes`, `provider_calls`, `records_merged`,
`records_overwritten`, `records_deleted` and `records_promoted` are derived from
an in-process mutation-operation log. This offline tool never appends to that
log, so the counters are zero by construction; `mutation_log_is_invariant: true`
records this property.

## Owner-decision rules

- Every finding stays visible; nothing is auto-resolved.
- No price is assigned or inferred by the tool.
- Exact duplicates of existing catalog records are reported and never written.
- Only an owner decision, with a dated attributable source and recorded change
  reason, may resolve a conflict. This tool does not perform that resolution.
