# Current Project State

**Last updated:** 2026-11-12  
**Repository:** CarAutopsy/carautopsy  
**Default branch:** `main`  
**Current mode:** GitHub + GitHub Actions development

## Confirmed completed

- PR #43 merged to `main`: prompt/schema contract documentation and schema tests. The owner explicitly waived the independent-audit prerequisite for that merge; the waiver did not satisfy issue #47.
- PR #49 merged: schema-aligned prompt builders and deterministic candidate/evidence validation helpers.
- PR #50 merged: DNS-pinned HTTPS retrieval primitive.
- PR #52 merged to `main`: owner-controlled source policy checks, robots handling, bounded extraction workers, and claim-level quote/locator evidence bindings.
- PR #53 merged into `feat/hive-source-policy-extraction`, not directly into `main`. Documentation PR #56 is open to bring its zero-bypass contract onto `main`.
- Issue #45 (no-retrieval safety stop) is closed; its invariants remain mandatory.

## Active Hive status

- Open issues: #37 (retrieval/provenance/runtime integration), #44 (candidate gate/prompt integration acceptance), #47 (independent third-party audit).
- Draft PR #57 wires the orchestration path through retrieval, researcher prompt, deterministic candidate gate, and two independent auditors. It preflights and caches evidence before proposal checkout/state overlay.
- PR #57 head `96a624ebcc422626fdc6d2600bdd86a3cc4d77b9`: 268 Python tests pass; catalog validation, module compilation, and Repository Audit pass. The audit reports one existing warning for missing `apps/web/package.json` and zero errors.
- This is not activation-ready: full retry/restart/state-reconciliation failure-path proof and independent external review remain outstanding.
- `data-connectors/approved-source-hosts.json` has an empty approved-host and source-policy list.
- `VERIFIED_RETRIEVAL_AVAILABLE = False`; `HIVE_RESEARCH_PAUSED` remains active.
- Full TCO mode calculates from the existing catalog and leaves the Hive research queue untouched; provider smoke-test routing remains separate.\n- No live OEM retrieval, paid provider calls, or vehicle research dispatch is authorized.
- The vehicle queue has 23 variants; failed candidate/audit records remain in `tasks/failed.json`. Do not automatically retry or promote them while paused.

## Immediate engineering sequence

1. Review and merge the documentation roadmap PR #56.
2. Review PR #57 with CodeRabbit/Copilot and resolve findings; keep it draft until its remaining integration tests are complete.
3. Complete end-to-end tests for proposal/state divergence, retries, restarts, and zero mutation on retrieval/policy failures.
4. Complete issue #47's independent audit and the external security review tracked under #37.
5. Obtain explicit owner authorization before considering activation.

See [ROADMAP.md](ROADMAP.md), [NEXT_ACTIONS.md](NEXT_ACTIONS.md), and [HIVE_PIPELINE_INTEGRATION.md](HIVE_PIPELINE_INTEGRATION.md).

## Operational constraints

- Do not add hosts or exact URLs to the approved manifest without owner review.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove the research pause as part of intermediate implementation PRs.
- Do not use paid provider calls or live source requests in unit/CI tests.
- Do not treat schema validity, quote presence, or HTTP 2xx as proof that a vehicle claim is true.
- Preserve two independent vendor PASS verdicts and required human review.
