# Draft PR: schema-aligned Hive prompts and pre-audit candidate gates

Status: specification and schema tests first; runtime implementation pending.

## Summary
Document researcher/auditor contracts, deterministic validation, evidence requirements and acceptance tests. Add executable tests against the actual catalog schema. Follow with prompt builders and orchestration changes only after review.

## Problem
Current model calls lack source retrieval yet ask for official specifications and retrieval dates. Nested names are unspecified. Model audits do not replace deterministic schema checks or retrieved evidence.

## Intended runtime change
Validate schema and task identity before paid audits; reject rather than repair model output. Supply explicit canonical fields and mark all external text untrusted. Require exact parsed PASS. When retrieval is unavailable, stop research before spending or state mutation. This deliberate operational stop is not present in this documentation commit.

## Non-goals
No retrieval implementation, factual verification, retry-budget redesign, state-race fix, tax-rule changes, automatic merge or unrelated cleanup.

## Validation checklist
- [ ] Execute schema-contract tests.
- [ ] Implement candidate-gate and prompt tests.
- [ ] Prove zero-spend/no-state-change behavior with orchestration tests.
- [ ] Validate Catalog and Repository Audit pass on final head SHA.
- [ ] Independent commit-bound audit completed.

## Remaining work
See HIVE_PROMPT_OVERHAUL.md and HIVE_PROMPT_TEST_PLAN.md. Lack of retrieval remains unresolved; do not label prompt changes as verified research.

AI-authored. Keep draft; no auto-merge.
