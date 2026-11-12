# Hive pipeline integration: zero-bypass contract

**Status:** implementation contract for the next runtime-integration change. This document does not enable retrieval, provider calls, or research.

## Required execution order

For each reserved queue task, the research path must perform these steps in order:

1. Read the reserved `variant_id`, `make`, and `model`; never accept or repair those values from model output.
2. Load the owner-controlled source manifest. An empty, malformed, stale, or ambiguous manifest is a hard stop.
3. Retrieve only exact URLs whose owner-reviewed policy explicitly includes the reserved variant ID. Check source terms and live robots.txt before each target request, using the existing pinned HTTPS transport.
4. Extract bounded text and structured document/page locator spans. Keep raw response bytes transient and never put full source bodies or untrusted instructions in the retry ledger.
5. Build the researcher prompt from the reserved task, repository schema, and retrieved evidence only. The researcher must have no network/browsing capability.
6. Parse the response as one JSON object and run the deterministic schema, identity, provenance, and claim-quote gate.
7. Only a validated candidate and the exact same bounded evidence bundle may be passed to independent auditors.
8. Preserve two independent vendor PASS verdicts and human review. Schema validity and exact quote presence do not establish semantic claim support.

## Mandatory zero-bypass proof

Tests must demonstrate:

- Empty or invalid owner manifest: zero target requests, zero researcher calls, zero auditor calls, zero queue/ledger/catalog writes.
- Terms or robots denial, unavailable robots, malformed directives, extraction failure, and transport rejection: zero researcher/auditor calls and no candidate publication.
- Malformed JSON, schema violation, reserved identity mismatch, undeclared source, URL mismatch, missing claim binding, forged locator, or quote mismatch: zero paid auditor calls.
- Accepted candidates: both independent auditors receive byte-for-byte equivalent candidate and evidence inputs; the candidate is not mutated between audits.
- Retry, restart, existing-proposal, and state-branch paths cannot skip retrieval or deterministic validation.
- Provider/auditor failures remain distinguishable from provenance rejection; no error body, raw source text, credentials, or secrets enter persisted state.

## Activation boundary

- Keep `VERIFIED_RETRIEVAL_AVAILABLE = False` until integration and all required proof are reviewed.
- Keep `HIVE_RESEARCH_PAUSED` active.
- Keep `data-connectors/approved-source-hosts.json` empty.
- Do not add live OEM URLs, perform live source retrieval, or spend provider tokens in unit/CI tests.
- This contract is not runtime implementation, end-to-end verification, or permission to activate research.

## Implementation sequence

1. Add a small orchestration seam that retrieves evidence, builds the prompt, parses and validates the candidate, and returns only a validated candidate/evidence pair.
2. Place that seam before any auditor invocation in `autonomous_pipeline.py`.
3. Ensure every retry/restart entry point reaches the same seam.
4. Add deterministic call-count and filesystem/ledger immutability tests around the seam.
5. Run the full Python suite, catalog validation, compilation, Repository Audit, and independent external security review on the exact final integration head.
