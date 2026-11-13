# Hive prompt overhaul test plan

Status: implementation and acceptance evidence for offline helpers; live pipeline integration and retrieval remain unverified.

## Implemented in this documentation commit
Executable schema-contract cases in tests/test_hive_schema_contract.py: minimal sparse record; all required root keys; make vs brand; offers array; source objects; confidence enum; negative power and mass; fractional monetary minor units; valid and invalid calendar dates with explicit FormatChecker; nullable fields; optional source URL. Current permissive schema gaps are documented separately rather than asserted as desirable behavior. These test the actual repository schema, not a copied schema.

## Implemented offline candidate-gate and prompt tests
The helper suite in `tests/test_hive_candidate.py` covers non-object/malformed candidates, exact reserved identity (`variant_id`, `identity.make`, `identity.model`), non-finite numbers, bounded and non-empty evidence, duplicate/missing source metadata, provenance URL matching, exact claim paths, source/locator/quote binding, missing claim coverage, offer country/currency/price evidence, input immutability, pipeline-owned metadata normalization and schema validation. The gate exempts only reserved `identity.make`/`identity.model` from identity claim evidence and `offers[].offer_id` from offer claim evidence; `variant_id` is checked separately against the task. Unknown values must follow the schema's nullability: omit optional non-nullable offer country/currency fields when unknown.

The prompt suite in `tests/test_hive_prompts.py` covers quotes, newlines, Unicode, untrusted-data boundaries, no-browsing instructions, shared evidence/schema inputs, schema-aware null handling, and exact reserved identity fields. These tests establish helper behavior only; they do not prove model obedience or live pipeline ordering.

## Remaining live-integration and retrieval tests
Before live research can resume, prove in the actual orchestration path that candidate parsing and validation occur before paid auditor calls; rejected candidates make zero paid calls; both independent auditors receive the same validated candidate/evidence bundle; and retries/restarts cannot bypass the gate. Use mocks and temporary repositories, not live paid calls. Also prove missing retrieval causes zero researcher/auditor/fallback calls, no checkout/commit/push/PR/state mutation, unchanged counters and a clear operational pause. Keep smoke-test/full-TCO routing unchanged. These integration and retrieval/security requirements remain under Issue #37.

## Evidence limits
Offline helper tests do not prove that the autonomous pipeline invokes the helpers before paid auditors, that retries cannot bypass validation, or that source retrieval is safe. No live provider calls, source retrieval, OEM access, or factual vehicle verification are performed by these unit tests. Hive remains paused pending the separate Issue #37 integration and security acceptance work.

## CI and audit evidence
Run python -m unittest discover -s tests -v and python -m compileall -q scripts tests. Record actual results against a full commit SHA; unexecuted tests are NOT_VERIFIED. Schema tests are not provenance verification or end-to-end proof. Independent reviewer must inspect final diff before merge.
