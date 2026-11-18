# CivLab → CarAutopsy Automation Reuse Assessment

**Status:** Discovery / design input  
**CarAutopsy baseline:** `main` at `0933695c814d452be3943a778177d06bf492ebfb`  
**CivLab source:** `CivLab-Project/civlab`  
**Tracking issue:** [#114](https://github.com/CarAutopsy/carautopsy/issues/114)  
**Scope:** Read-only repository inspection; no runtime or security policy changed by this assessment.

## 1. Executive summary

CivLab provides a valuable history of building and hardening an autonomous engineering pipeline. The retrieved PR history contains **205 closed PRs**, of which **197 were merged** and **8 were closed without merge**, spanning 2026-10-20 through 2026-11-09. No open CivLab PRs were returned in the inspection.

The highest-value lesson is not to copy CivLab wholesale. It is to reuse the engineering controls that were learned through its iterations:

1. One canonical orchestration controller.
2. Explicit task contracts and allow-listed paths.
3. Separation of generation, deterministic verification, independent audit, and publication.
4. Typed failure classes with bounded, evidence-backed correction.
5. Durable state, explicit reconciliation, and owner decisions.
6. Read-only operational reporting.
7. Tests for workflow permissions, job dependencies, artifacts, and fail-closed behavior.

CarAutopsy already has a mature Hive domain pipeline. Its state branch, versioned outcome records, source/provenance controls, independent auditor quorum, and read-only roadmap evidence collector should be preserved. CivLab's engineering-agent pipeline should be a separate capability, not a replacement for Hive.

## 2. PR history inventory

The following categories are overlapping title-keyword groupings, not exclusive partitions:

| Theme | Matched merged PRs | What the history covers |
|---|---:|---|
| Task contracts / roadmap | 71 | Task eligibility, acceptance contracts, roadmap progression |
| Provider / AI | 24 | Provider routing, response parsing, token limits, pricing |
| Workflow / orchestration | 17 | Dispatch, loop control, canonical workflow |
| Audit / review / publication | 18 | Audit gates, evidence-bound reviews, draft-PR publishing |
| Docs / reporting | 17 | Owner digest, roadmap sync, runbooks, status |
| Ledger / recovery | 11 | Persistent state, failure classes, reconciliation, owner decisions |
| Security / sandbox | 8 | Allow-lists, execution isolation, protected paths, gates |

### 2.1 High-value PR shortlist

**Prototype and foundational controls**
- [#26](https://github.com/CivLab-Project/civlab/pull/26) — security-gated DeepSeek/Gemini proposal prototype. Introduced task selection, diagnostics, sandbox boundary, and regression tests.
- [#31](https://github.com/CivLab-Project/civlab/pull/31) — AI Audit Protocol v2.1. Established shared audit expectations and agent instructions.
- [#32](https://github.com/CivLab-Project/civlab/pull/32) — bounded one-shot coding pilot and verified draft-PR publisher.
- [#36](https://github.com/CivLab-Project/civlab/pull/36) — hourly autonomous improvement loop.
- [#37](https://github.com/CivLab-Project/civlab/pull/37) and [#38](https://github.com/CivLab-Project/civlab/pull/38) — opt-in live provider smoke test and manual workflow.
- [#46](https://github.com/CivLab-Project/civlab/pull/46) — bound review artifact creation and upload.

**Boundaries, failure handling, and provider architecture**
- [#57](https://github.com/CivLab-Project/civlab/pull/57) — pilot window, task allow-list, draft-PR cap, persistent ledger, runtime and pricing structures.
- [#68](https://github.com/CivLab-Project/civlab/pull/68) — stricter proposal JSON response contract.
- [#72](https://github.com/CivLab-Project/civlab/pull/72) — protects existing regression-test files from generated proposals. The same PR also included Python bytecode cache files; do not reproduce that artifact mistake.
- [#73](https://github.com/CivLab-Project/civlab/pull/73) — narrows the task allow-list.
- [#87](https://github.com/CivLab-Project/civlab/pull/87) — typed failure taxonomy and owner-controlled stop clearance.
- [#88](https://github.com/CivLab-Project/civlab/pull/88) — provider registry and dispatch routing.
- [#90](https://github.com/CivLab-Project/civlab/pull/90) — budget-gated improvement loop.
- [#92](https://github.com/CivLab-Project/civlab/pull/92) — separate, gated draft-PR publishing.
- [#94](https://github.com/CivLab-Project/civlab/pull/94) — documents the limitation that required environment reviewers were unavailable on the then-current repository plan.

**Single-controller and correction-loop lessons**
- [#123](https://github.com/CivLab-Project/civlab/pull/123) — makes `agent-pipeline.yml` the single improvement loop and removes the competing workflow after gate divergence.
- [#126](https://github.com/CivLab-Project/civlab/pull/126) — regression tests for rerun refusal and publication owner gate.
- [#136](https://github.com/CivLab-Project/civlab/pull/136) — provider errors do not consume the code-revision allowance.
- [#177](https://github.com/CivLab-Project/civlab/pull/177) — adds a distinct verification-failure class and last-feedback ledger field.
- [#178](https://github.com/CivLab-Project/civlab/pull/178) — evidence-based verification failures, bounded feedback, and exhausted-task skipping.
- [#179](https://github.com/CivLab-Project/civlab/pull/179) — records verification failure evidence in the workflow contract.

**Operational reporting and roadmap synchronization**
- [#180](https://github.com/CivLab-Project/civlab/pull/180) — owner digest and roadmap sync specification.
- [#181](https://github.com/CivLab-Project/civlab/pull/181) — attempt timestamps and cancelled outcomes.
- [#182](https://github.com/CivLab-Project/civlab/pull/182) — deterministic roadmap-sync proposal script and tests.
- [#183](https://github.com/CivLab-Project/civlab/pull/183) — owner decisions recorded in the ledger.
- [#184](https://github.com/CivLab-Project/civlab/pull/184) — read-only owner digest with regression tests.
- [#185](https://github.com/CivLab-Project/civlab/pull/185) — brings owner-digest changes under security checks.

**Task-contract refinement**
- [#204](https://github.com/CivLab-Project/civlab/pull/204), [#206](https://github.com/CivLab-Project/civlab/pull/206), [#207](https://github.com/CivLab-Project/civlab/pull/207), [#208](https://github.com/CivLab-Project/civlab/pull/208), [#209](https://github.com/CivLab-Project/civlab/pull/209) — P30 task contract, eligibility, acceptance-shape corrections, and owner-controlled revision ceiling. These demonstrate why task specifications and acceptance criteria need iterative validation rather than simply raising retry limits.

## 3. Component comparison

| Capability | CivLab source | CarAutopsy current implementation | Decision |
|---|---|---|---|
| Task contract and eligibility | `agent-policy.json`, `agent-tasks/*.md`, task selector | Issue/roadmap proposal and apply modules; Hive reserved queue identity | **Adapt** for a separate engineering-agent task contract |
| Persistent execution ledger | `pilot_state.py`, `pilot_runtime.py`, GitHub-backed SQLite adapter | `hive/state` branch with queue/failed JSON, digest trailers, proposal ancestry and reconciliation acknowledgement | **Preserve Hive state**; borrow transaction/failure semantics only where needed |
| Typed outcomes | CivLab `FAILURE_CLASSES` and bounded diagnostics | `hive_outcomes.py` has versioned outcome codes, retry counters, defect categories, manual-review quarantine | **Preserve existing**; compare semantics and fill only proven gaps |
| Provider routing | `provider_registry.py` with role order and endpoint checks | `autonomous_pipeline.py` has provider configuration/dispatch; `provider_retry.py` handles Gemini transient retries and fallback | **Adapt selectively**; avoid changing independent-vendor quorum or fallback behavior |
| Sandbox | `pipeline_security.py` stages allow-listed files and runs isolated typecheck/tests | Hive validates research candidates/evidence; it is not an engineering-code execution sandbox | **Reuse for a separate code-generation pipeline**, not Hive research |
| Independent review | Provider audit bound to proposal digest | Hive runs two independent vendor audits over validated candidate/evidence | **Preserve** Hive quorum; engineering-code audit needs its own contract |
| Publication | `candidate_publisher.py`, `pilot_publish.py`, separate publish job | Hive research branch/PR workflow; TCO full route has a separate publication/commit path | **Adapt** evidence-bound draft PR for engineering code; do not conflate with research PRs |
| Owner digest | `owner_digest.py`, read-only SQLite query | At the inspected baseline, workflow summaries and read-only issue-roadmap artifacts; the additive Hive JSON digest is now proposed in CarAutopsy PR #116 | **Adapted** without introducing SQLite |
| Roadmap sync | `roadmap_sync.py`, proposes status from merged PRs/owner decisions/ledger | `issue_roadmap_sync.py`, evidence collector and owner-approved apply plan | **Preserve CarAutopsy design**; borrow report and evidence discipline |
| Workflow tests | Pipeline gate tests assert job graph, permission boundaries and artifact contracts | Existing Hive schema, gate, retry, state, and issue-roadmap tests | **Extend** with workflow contract tests |

## 4. Important CivLab caveats

### 4.1 Monetary budget enforcement must be proven, not assumed

CivLab's current `automation/agent-policy.json` explicitly says:
- `enforcementImplemented: false`
- `monetaryBudgetEnforced: false`

CivLab's `pilot-pricing.json` contains reviewed model rates and token bounds, and the runtime has reservation/settlement logic. However, the policy itself still records the overall monetary enforcement claim as false, and its notes identify prompt-size enforcement as a hardening follow-up. Therefore, the ledger and pricing implementation are useful design references, but they are not sufficient evidence to claim a complete hard spend ceiling. CarAutopsy must require executable tests for every spend boundary before describing a budget as enforced.

### 4.2 Environment declarations are not approvals by themselves

CivLab's runbook records that required environment reviewers were unavailable on its then-current plan. The workflow's `environment:` declarations did not create an effective reviewer gate. CarAutopsy must verify actual repository protection configuration and available permissions; a YAML environment name is not proof of human approval.

### 4.3 Uncertain writes require reconciliation

CivLab intentionally leaves an attempt unresolved when a branch update or PR submission may have succeeded remotely but the response is uncertain. It checks the ref/PR and reconciles rather than blindly retrying. This is an important invariant for any future CarAutopsy engineering publisher.

### 4.4 Keep candidate code away from credentials

CivLab separates the candidate verification container from provider secrets and GitHub write credentials. Its security status also distinguishes mocked boundary tests from proof of real Docker isolation or end-to-end readiness. CarAutopsy should adopt the separation and preserve the distinction between test evidence and live proof.

### 4.5 Follow-up PR lineage: what was corrected after the first design

The selected PRs are a sequence of design corrections, not independent features to copy:

- **One controller, with explicit permission review (#123–#127).** #123 removed the competing hourly workflow after its gates diverged and made `agent-pipeline.yml` canonical. The same change explicitly granted `contents: write` to generation and failure-finalization jobs, so the lesson is not simply “one workflow”: job-level write permissions still need narrow justification. #124 recorded that monetary enforcement remained false rather than claiming it was complete. #125 documented that its exit criterion was only partially proven; #126 added rerun-refusal tests but explicitly left existing-draft detection open. #127 then added an existing-publication check before writes and left uncertain publication attempts unresolved for reconciliation.
- **Provider faults are not task defects (#87, #136).** The failure taxonomy was refined so transient provider errors are retried separately and do not consume the code-revision allowance. CarAutopsy already distinguishes provider transport, response format, provenance and quality outcomes; compare semantics rather than transplanting CivLab's classes wholesale.
- **Verification feedback is evidence-bound (#177–#179).** The sequence added a distinct verification-failure class, bounded feedback, exhausted-task skipping, and durable failure evidence. The reusable principle is that a correction attempt must be grounded in a specific verification result, not a generic retry prompt.
- **Owner reporting and roadmap decisions are separate, read-only proposals (#180–#185).** #180 specified the digest/sync behavior; #181 added attempt timestamps and a cancelled outcome; #182 created a deterministic roadmap proposal script; #183 persisted explicit owner decisions; #184 added a read-only digest; and #185 added those files/tests to the security-check path. This sequence supports the additive Hive digest, while CarAutopsy keeps its JSON state branch and owner-approved roadmap apply path.

The follow-up history also shows why a checked box or a successful unit test must not be treated as proof of live branch protection, hard monetary enforcement, sandbox isolation, or publication safety. Those claims require their own observable evidence.

## 5. CarAutopsy-specific observations

### 5.1 Existing Hive controls are already strong

Inspected CarAutopsy modules include:
- `scripts/hive_state.py`: dedicated state branch, SHA-256 ledger trailers, proposal-head ancestry and explicit reconciliation acknowledgement.
- `scripts/hive_outcomes.py`: versioned outcome schema, allow-listed failure codes, bounded counters, defect categories and manual-review quarantine.
- `scripts/hive_orchestration.py`: reserved task → evidence → researcher → deterministic candidate validation → two independent auditors.
- `scripts/hive_research_gate.py`: fail-closed research pause.
- `scripts/hive_audit.py`: strict PASS/FAIL verdict parser.
- `scripts/issue_roadmap_controller.py`, `issue_roadmap_evidence.py`, `issue_roadmap_sync.py`, `issue_roadmap_apply.py`: read-only issue intake, exact-head PR/check evidence, deterministic reconciliation and owner-approved apply planning.

Do not replace these with CivLab's SQLite ledger or roadmap controller. The data models and trust boundaries are different.

### 5.2 Separate the engineering-code workflow from Hive research

Hive's job is to produce sourced vehicle research candidates, not arbitrary repository code. The proposed engineering agent should have a separate workflow and task contract. It should never inherit Hive's source allow-list or research readiness flag as authorization to execute code.

### 5.3 Existing TCO write boundary needs its own review

The current `.github/workflows/autonomous-pipeline.yml` has:
- A read-only issue-roadmap crawler job.
- A research-only Hive path that is explicitly paused by `VERIFIED_RETRIEVAL_AVAILABLE = False`.
- A separate manually dispatched `full` TCO route that bypasses the research-only gate.

The inspected full TCO path in `scripts/autonomous_pipeline.py` commits and pushes to `main`; the workflow job has `contents: write` and checkout credentials persisted. This is not evidence that the paused Hive research path is active. It is an adjacent write boundary that should be reviewed separately before increasing automation scope. Do not silently copy or broaden it as part of this initiative.

### 5.4 Existing test coverage and concrete gaps

| Reuse candidate | CarAutopsy implementation | Existing regression coverage | Assessment |
|---|---|---|---|
| Task contracts / eligibility | `issue_roadmap_controller.py`, `issue_roadmap_proposal.py`, `issue_roadmap_evidence.py`, `issue_roadmap_sync.py`, `issue_roadmap_apply.py`; Hive task identity in `hive_orchestration.py` | `test_issue_roadmap_controller.py`, `test_issue_roadmap_evidence.py`, `test_issue_roadmap_sync.py`, `test_issue_roadmap_apply.py`, `test_hive_orchestration.py` | Strong existing read-only intake/evidence/owner-apply path. Do not replace it with CivLab's selector. |
| Persistent state / recovery | `hive_state.py` | `test_hive_state.py`, `test_hive_end_to_end_state_reconciliation.py`, `test_hive_restart_interruption.py` | Strong branch ancestry, ledger digest, interrupted-run and reconciliation coverage. Preserve JSON state model. |
| Typed outcomes / retries | `hive_outcomes.py`, `hive_orchestration.py`, `provider_retry.py` | `test_hive_outcomes.py`, `test_hive_orchestration_retry.py`, `test_hive_retry_recovery.py`, `test_provider_retry.py` | Existing retry classes are domain-specific and bounded. Crosswalk only where a missing failure distinction changes retry/stop behavior. |
| Source policy / evidence | `hive_source_policy.py`, `hive_source_retrieval.py`, `hive_evidence.py`, `hive_source_extract.py` | `test_hive_source_policy.py`, `test_hive_source_retrieval.py`, `test_hive_evidence.py`, `test_hive_pipeline_preflight.py`, `test_hive_pipeline_robots_denial.py`, `test_hive_pipeline_target_failure.py` | This is Hive's distinct provenance boundary; do not transplant engineering-code sandbox assumptions into it. |
| Independent audit | `hive_audit.py`, `hive_orchestration.py` | `test_hive_audit.py`, `test_hive_orchestration.py`, `test_hive_orchestration_zero_bypass.py` | Exact PASS parser, two-vendor quorum and zero-bypass tests already exist. Preserve quorum. |
| Publication | `hive_pr.py` and the separate TCO publication path | `test_hive_pr.py`, plus TCO-specific tests | No general-purpose engineering-code publisher/sandbox is established by these tests. Reuse CivLab publication only in a separately gated engineering pipeline. |
| Owner digest | Proposed `hive_owner_digest.py` and `hive-owner-digest.yml` in CarAutopsy PR #116 | New `tests/test_hive_owner_digest.py` in PR #116 | Additive, read-only adaptation. It reads a verified `hive/state` snapshot when present and labels the main fallback when absent. |
| Workflow graph / permissions | `.github/workflows/autonomous-pipeline.yml` | `test_hive_research_gate.py`, `test_hive_pipeline_preflight.py`, `test_hive_orchestration_zero_bypass.py` | Runtime gates are tested; a dedicated YAML-level contract suite for job permissions, dependencies, schedule isolation and artifact boundaries remains a gap. |

The most important remaining Phase 1 gap is workflow-contract testing. Add tests that assert the research pause remains fail-closed, the issue crawler and owner digest retain read-only permissions, and the separate TCO `full` route cannot silently expand into Hive dispatch or broader publication rights.

## 6. Recommended migration sequence

### Phase 0 — inventory and evidence map
- [x] Retrieve closed CivLab PR history and calculate merged/closed counts.
- [x] Categorize the PR history by major automation themes.
- [x] Select high-value source PRs and inspect their changed-file lists.
- [x] Compare CivLab core components against current CarAutopsy modules.
- [x] Complete follow-up/fix lineage review for the shortlisted PRs, including #123–#127, #136, #177–#185.

### Phase 1 — architecture reuse matrix
- [x] Map shortlisted CivLab components to exact CarAutopsy modules and existing tests; record the remaining workflow-contract coverage gap.
- [ ] Mark each candidate as reuse, adapt, preserve, or reject.
- [ ] Identify duplicate state, provider, retry, workflow, and roadmap capabilities before implementation.

### Phase 2 — design
- [ ] Define a separate CarAutopsy engineering-agent workflow.
- [ ] Define trusted task contracts, allowed paths, immutable source snapshot, and task reservation.
- [ ] Define isolated code verification and evidence artifacts.
- [ ] Define independent audit and a separate draft-PR publication gate.
- [ ] Define failure taxonomy, bounded correction, reconciliation, and owner digest.
- [ ] Specify hard spend limits and prove their enforcement in tests.

### Phase 3 — implementation
- [ ] Deliver small isolated PRs, one subsystem at a time.
- [ ] Add no-secret regression tests for contracts, permissions, job graph, artifacts, and fail-closed behavior.
- [ ] Obtain independent audits before merge.
- [ ] Do not enable recurring or paid execution as part of the initial implementation.

### Phase 4 — controlled proof
- [ ] Run a no-secret end-to-end dry run.
- [ ] Run an owner-watched provider smoke test only after explicit approval.
- [ ] Prove sandbox isolation and artifact binding.
- [ ] Prove publication uncertainty/reconciliation behavior.
- [ ] Enable any recurring execution only after a separate owner decision.

## 7. Initial recommended priorities

1. **Read-only Hive owner digest** — implemented in draft CarAutopsy PR #116, adapted from CivLab W6 (#180–185) to Hive JSON state without introducing SQLite.
2. **Workflow contract tests** — assert that research stays paused until readiness is explicit, crawler permissions remain read-only, and the TCO write path stays isolated.
3. **Engineering task contract + sandbox design** — reuse CivLab #26/#32/#57/#92/#123 concepts for a separate engineering-code pipeline.
4. **Outcome taxonomy crosswalk** — compare Hive's existing outcome codes to CivLab's failure classes; only add missing distinctions that materially improve retry or stop decisions.
5. **Provider registry review** — decide whether to centralize the existing provider list without changing vendor independence, provider fallback, or model defaults.

## 8. Source references

### CivLab code
- [Automation directory](https://github.com/CivLab-Project/civlab/tree/main/automation)
- [Agent pipeline workflow](https://github.com/CivLab-Project/civlab/blob/main/.github/workflows/agent-pipeline.yml)
- [Pipeline security boundary](https://github.com/CivLab-Project/civlab/blob/main/automation/pipeline_security.py)
- [Failure ledger](https://github.com/CivLab-Project/civlab/blob/main/automation/pilot_state.py)
- [Provider registry](https://github.com/CivLab-Project/civlab/blob/main/automation/provider_registry.py)
- [Owner digest](https://github.com/CivLab-Project/civlab/blob/main/automation/owner_digest.py)
- [Roadmap sync](https://github.com/CivLab-Project/civlab/blob/main/automation/roadmap_sync.py)
- [Pilot runbook](https://github.com/CivLab-Project/civlab/blob/main/automation/PILOT_RUNBOOK.md)
- [Security status](https://github.com/CivLab-Project/civlab/blob/main/automation/PIPELINE_SECURITY_STATUS.md)

### CarAutopsy code
- [Hive orchestration](https://github.com/CarAutopsy/carautopsy/blob/0933695c814d452be3943a778177d06bf492ebfb/scripts/hive_orchestration.py)
- [Hive state](https://github.com/CarAutopsy/carautopsy/blob/0933695c814d452be3943a778177d06bf492ebfb/scripts/hive_state.py)
- [Hive outcomes](https://github.com/CarAutopsy/carautopsy/blob/0933695c814d452be3943a778177d06bf492ebfb/scripts/hive_outcomes.py)
- [Issue roadmap evidence](https://github.com/CarAutopsy/carautopsy/blob/0933695c814d452be3943a778177d06bf492ebfb/scripts/issue_roadmap_evidence.py)
- [Issue roadmap sync](https://github.com/CarAutopsy/carautopsy/blob/0933695c814d452be3943a778177d06bf492ebfb/scripts/issue_roadmap_sync.py)
- [Autonomous workflow](https://github.com/CarAutopsy/carautopsy/blob/0933695c814d452be3943a778177d06bf492ebfb/.github/workflows/autonomous-pipeline.yml)
- [Autonomous pipeline](https://github.com/CarAutopsy/carautopsy/blob/0933695c814d452be3943a778177d06bf492ebfb/scripts/autonomous_pipeline.py)
