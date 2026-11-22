# Offline evidence-sprint workflow

**Status:** implementation support for PR #152. Offline, deterministic, and
owner-controlled. No retrieval, provider, secret, staging or catalog write.

## Purpose

`scripts/evidence_sprint.py` turns the committed 36 `unavailable` candidates from
`docs/research/pilot-gap-price-candidates.json` into a structured sprint artifact
using the committed wave/gap-class assignment table at
`docs/research/evidence-sprint-002-assignments.json`.

The three waves and their exact model assignments, and the six gap classes, are
preserved from `docs/research/pilot-evidence-sprint-002.md` and
`docs/operations/PILOT_EVIDENCE_GAP_PLAN.md`.

## CLI

```bash
# Validate only; writes nothing
python scripts/evidence_sprint.py --check

# Emit a deterministic artifact under docs/research or docs/operations
python scripts/evidence_sprint.py \
  --candidates docs/research/pilot-gap-price-candidates.json \
  --assignments docs/research/evidence-sprint-002-assignments.json \
  --report docs/research/pilot-evidence-sprint-002-output.json
```

Exit codes: `0` success/check, `2` CLI error, `3` validation or unsafe-path error.

Report paths under `catalog/`, `catalog/variants/` or `staging/` are refused. Only
`docs/research/` and `docs/operations/` are accepted.

## Output fields

Each entry contains exactly:

`brand`, `model`, `tier`, `wave`, `gap_class`, `required_evidence`,
`best_source_type`, `next_action`, `next_evidence_batch`, `remain_unavailable`.

The report also carries `candidate_sha256`, `assignment_sha256`, `candidate_count`,
`wave_counts`, `gap_class_counts`, and zero counts for `catalog_writes`,
`staging_writes` and `provider_calls`. No timestamp is emitted, so rerunning on
unchanged inputs produces byte-identical output.

## Validation rules

The pipeline rejects:

- missing required fields;
- unknown gap classes;
- invalid wave assignments;
- duplicate model identities (case-insensitive);
- unsupported price claims (a sprint entry must remain `unavailable`);
- unsupported provenance claims (empty source/action fields);
- candidate/assignment count mismatches;
- report paths outside the allowed documentation directories.

## Owner boundary

This workflow prepares research structure only. It does not assign a price,
fetch a source, activate a provider, create a staging record, or modify the
catalog. Every candidate remains `unavailable` until an owner-reviewed evidence
correction with a dated, attributable source is approved.
