# Hive prompt overhaul test plan

Status: schema, candidate, prompt and mocked orchestration tests are implemented. Production retrieval and factual source verification remain deliberately disabled/unverified.

## Implemented in this documentation commit
Executable schema-contract cases in tests/test_hive_schema_contract.py: minimal sparse record; all required root keys; make vs brand; offers array; source objects; confidence enum; negative power and mass; fractional monetary minor units; valid and invalid calendar dates with explicit FormatChecker; nullable fields; optional source URL. Current permissive schema gaps are documented separately rather than asserted as desirable behavior. These test the actual repository schema, not a copied schema.

## Implemented offline candidate-gate and prompt tests
The helper suite in `tests/test_hive_candidate.py` covers non-object/malformed candidates, exact reserved identity (`variant_id`, `identity.make`, `identity.model`), non-finite numbers, bounded and non-empty evidence, duplicate/missing source metadata, provenance URL matching, exact claim paths, source/locator/quote binding, missing claim coverage, offer country/currency/price evidence, rejection of whitespace-only decision values, input immutability, pipeline-owned metadata normalization and schema validation. The gate exempts only reserved `identity.make`/`identity.model` from identity claim evidence and `offers[].offer_id` from offer claim evidence; `variant_id` is checked separately against the task. Unknown values must follow the schema's nullability: omit optional non-nullable offer country/currency fields when unknown.

The prompt suite in `tests/test_hive_prompts.py` covers quotes, newlines, Unicode, untrusted-data boundaries, no-browsing instructions, shared evidence/schema inputs, schema-aware null handling, and exact reserved identity fields. These tests establish helper behavior only; they do not prove model obedience or live pipeline ordering.

## Implemented mocked orchestration tests
The Hive orchestration, retry/restart and research-gate suites exercise the helper ordering with injected synthetic evidence and provider callbacks. They verify that candidate parsing and deterministic validation precede auditor invocation, both independent auditors receive the same validated candidate/evidence, rejected candidates do not reach auditors, and unavailable retrieval stops before provider calls and durable state mutation. These are mocked/local tests; they do not authorize or exercise production retrieval.

## Remaining production acceptance
The orchestration path is implemented and invokes candidate validation before the auditors, but production remains paused. Before production retrieval or paid research can resume, the owner must complete the security review and five-service AI cross-review; review source relevance and automated-access terms for each exact URL; approve any source manifest entries; verify robots/policy behavior, retrieval/extraction bounds and claim-support evidence; review exact-head CI/security results; and explicitly authorize activation. Issue #37 tracks these requirements. Keep `VERIFIED_RETRIEVAL_AVAILABLE = False`, the source manifest empty, and Hive paused until then.

## Evidence limits
The helper and orchestration tests establish deterministic behavior against synthetic inputs and mocks. They do not establish OEM source permission, live retrieval correctness, source authenticity, semantic claim support, vehicle facts, statutory rules or production readiness. No live provider calls, paid auditor calls, source retrieval or factual vehicle verification are performed by these tests.

## CI and audit evidence
Run python -m unittest discover -s tests -v and python -m compileall -q scripts tests. Record actual results against a full commit SHA; unexecuted tests are NOT_VERIFIED. Schema tests are not provenance verification or end-to-end proof. Independent reviewer must inspect final diff before merge.
