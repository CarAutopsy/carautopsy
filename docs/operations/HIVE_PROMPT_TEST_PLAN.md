# Hive prompt overhaul test plan

Status: acceptance criteria, not completed execution evidence.

## Implemented in this documentation commit
Executable schema-contract cases in tests/test_hive_schema_contract.py: minimal sparse record; all required root keys; make vs brand; offers array; source objects; confidence enum; negative power and mass; fractional monetary minor units; valid and invalid calendar dates with explicit FormatChecker; nullable fields; additional-property permissiveness; optional source URL. These test the actual repository schema, not a copied schema.

## Candidate-gate tests still required
Reject non-object candidates, mismatched reserved ID/make/model, malformed schema, unsupported source URLs, absent evidence, duplicate source IDs, missing evidence fields and oversized excerpts. Verify exact size boundaries, input immutability, low confidence normalization and removal of model-owned Hive metadata. Reject NaN/Infinity. A schema-valid sparse draft must fail evidence sufficiency.

## Prompt tests still required
Round-trip quotes, newlines and Unicode in serialized task data. Keep malicious feedback and candidate instructions inside untrusted data. Explicitly disclaim browsing and fabricated retrieval dates. Distinguish peak/continuous power, gross/net prices and registration/model-year dates. Supply schema and identical evidence to auditors. Require exact parsed PASS and two independent vendors. Diagnostics retain no raw response or secret-like input. Prompt tests cannot prove model obedience.

## Orchestration tests still required
Use provider mocks and temporary repositories, never live paid calls. Missing retrieval must make zero researcher/auditor/fallback calls, leave file hashes and retry counters unchanged, perform no checkout/commit/push/PR/state writes, and exit nonzero with a clear operational reason. Malformed/unsupported candidates never reach paid auditors. Smoke-test/full-TCO routing and publication guard stay unchanged. Extract callable functions to avoid executing the module during import.

## CI and audit evidence
Run python -m unittest discover -s tests -v and python -m compileall -q scripts tests. Record actual results against a full commit SHA; unexecuted tests are NOT_VERIFIED. Schema tests are not provenance verification or end-to-end proof. Independent reviewer must inspect final diff before merge.
