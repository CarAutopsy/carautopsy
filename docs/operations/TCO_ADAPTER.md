# TCO adapter

**Status:** PR #154 implementation. The adapter prepares TCO-ready inputs only.
It does not calculate TCO, change the Austrian TCO engine, alter tax rules, or
write catalog or staging records.

## CLI

```bash
# validate only
python scripts/tco_adapter.py --check --input tests/fixtures/tco_adapter/end_to_end.json

# deterministic report under docs/research or docs/operations
python scripts/tco_adapter.py \
  --input tests/fixtures/tco_adapter/end_to_end.json \
  --report docs/research/tco-adapter-report.json
```

Exit codes: `0` success/check, `2` CLI error, `3` validation or unsafe-path error.
Report paths under `catalog/`, `catalog/variants/` and `staging/` are refused.

## Supported mapping

Only fields explicitly consumed by `scripts/tco_engine.py` are mapped. The
adapter never widens this set:

- identity: make, model, variant name, powertrain, vehicle class;
- registration: first registration date;
- dimensions: max permissible mass, own weight;
- performance: electric motor power or combustion engine power;
- emissions: WLTP CO2;
- energy: BEV consumption (real-world / WLTP) or fuel consumption;
- offer: excl-VAT purchase price and list price;
- provenance confidence.

Powertrain-specific mandatory inputs follow `validate_tco_readiness.py`: BEV
records require electric motor power and electric consumption; combustion, HEV
and PHEV records require combustion power and fuel consumption. All records
require an excl-VAT price; no VAT conversion is inferred by the adapter.

## Evidence statuses

Each mapped field retains one of four statuses:

| Status | Meaning |
|---|---|
| `verified` | Dated, attributable supporting evidence |
| `approximate` | Approximate price/proxy; provisional use only |
| `unavailable` | Field absent in evidence; left out of TCO input |
| `owner_decision_required` | Evidence present but insufficient; field withheld |

A record is accepted only when all applicable mandatory inputs are present,
valid, and not withheld for owner decision. Approximate values are labelled,
never promoted to verified. Missing values are never defaulted.

## Dry-run report

The deterministic report lists, per record:

- `mapped_fields` and `unmapped_fields`;
- `missing_mandatory_inputs`;
- `approximate_fields`, `unavailable_fields`, `owner_decision_fields`;
- `validation_failures`;
- `provenance` with status, source URL/date, confidence, price tier, market and
  VAT basis for each mapped or withheld field;
- `tco_input` only for accepted records;
- `tco_calculated: false` and `engine_invoked: false` always.

The top level records `catalog_writes: 0`, `staging_writes: 0`,
`provider_calls: 0`, `tco_calculations: 0` and `business_rules_changed: false`.

## Owner-review boundary

This adapter is a preparation step. Actual TCO calculation, staging, catalog
writing and provider activation require separate owner authorization. No tax
formula, statutory rate, depreciation assumption or existing calculation output
is changed by this tool.
