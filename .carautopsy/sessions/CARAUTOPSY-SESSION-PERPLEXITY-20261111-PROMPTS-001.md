# Prompt overhaul session handover

Date: 2026-11-11. Agent: PERPLEXITY. Repository: CarAutopsy/carautopsy. Working branch: fix/hive-schema-grounded-prompts. Branch was created from 8115c49893bf4847e28b4689bebf34c507b77bc2.

Owner requested schema-aligned prompts, documentation, tracking artifacts and executable schema-validation tests. This commit documents the design and adds schema-contract tests only. No live pipeline behavior changes, provider calls or merge authorized by this artifact.

Next: execute tests, open a draft PR, create bounded follow-up issues after checking duplicates, implement prompt/gate modules and no-retrieval orchestration stop, obtain independent review. Each external write needs its own confirmation.

Known limitation: runtime source retrieval is absent; schema validity does not prove facts. Do not claim full implementation, test success, CI success or independent audit until verified. See docs/operations/HIVE_PROMPT_OVERHAUL.md and HIVE_PROMPT_TEST_PLAN.md.
