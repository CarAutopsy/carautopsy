# SENTINEL — Quality Assurance Protocol v1.0

Status: PROPOSED — owner review required. Date: 2026-11-26.
Scope: FareGraph and CarAutopsy; all human and AI contributors, authors,
reviewers, researchers, operators, coordinators and owner acting in those roles.
This is a governance proposal, not an activation or a claim of runtime enforcement.

## 1. Authority and scope

Upon owner acceptance, every contributor MUST apply this protocol to substantive
engineering work, research, documentation, audits, operational decisions and
owner-facing answers, including GPT, Gemini, Qwen, DeepSeek, OpenCode,
Perplexity, Copilot and future agents. No human or model is exempt from evidence
integrity. Existing repository safety, lane ownership, privacy, handover,
release and merge rules remain binding. SENTINEL adds requirements; it does not
relax any existing gate or authorize work, network access, spend, source
activation, private-code disclosure, credentials, or merges. Only the owner
may authorize scoped changes and merge under existing rules.

## 2. Three pre-report review passes

A — Requirements: record the work order, authorization, exact base, allowed
paths, acceptance criteria and prior findings. Search current code and
historical/open PRs for existing functionality. Assign exclusive ownership.
Maintain a requirement-to-evidence matrix; mark missing requirements explicitly.
Do not claim a gap merely because a proposed filename is absent.

B — Adversarial: inspect the actual diff or research claims, not just a summary.
Challenge assumptions, malformed input, boundaries, permissions, failure
propagation, data flow, semantic correctness, regressions and resource limits.
Tests must assert intended behavior, not only field presence or hardcoded
success. Check every prior finding individually. For research, verify primary
sources, scope, dates, applicability and uncertainty. For answers, check factual
claims, arithmetic, citations, authorization and whether the requested action
actually occurred. Repair within scope and repeat affected checks.

C — Evidence: reconcile every material claim with the actual artifact, exact
SHA, test command, exit code, counts, output and timestamp where applicable.
Distinguish executed tests, observed CI, static inspection, reported results,
and inference using existing evidence tags. Never relabel an author report
as independently observed execution. Record unrun, failed, skipped and
unavailable checks explicitly. Verify final published head and changed paths.
Never fabricate a test, citation, action, review, or successful outcome.

Each pass records a concise checklist, findings, disposition and evidence
references, not private reasoning. The same author doing three passes is
self-review, not independent certification. All material findings must be
corrected or explicitly remain open; no silent downgrades.

## 3. Verification and independent review

Code changes require focused tests, repository-required full regression, lint,
handover and applicable security checks, with exact candidate SHA and isolated
clean worktree evidence. Documentation-only work requires link, scope, factual
and policy consistency checks plus applicable repository checks; any proposed
not-applicable check needs a reason and must respect existing mandatory gates.
A test count alone is never an acceptance criterion.

An independent non-author reviewer must inspect the exact candidate, original
requirements, previous findings and evidence, and record PASS, CHANGES_REQUESTED
or REVIEW_UNAVAILABLE. A reviewer must not have authored the candidate change;
a separate model name alone does not prove independence. For a substantive
owner-facing answer, use independent review when available and required by
the work order; otherwise disclose self-review only, never imply certification.
Do not transmit private material to external reviewers without permission.

Any new commit invalidates prior exact-head certification, including a
documentation-only or handover-only commit. A reviewer may explicitly verify
unchanged relevant artifacts and issue a new SHA-bound certificate; never
silently carry approval forward. A base change or changed acceptance criteria
also requires impact assessment and renewed affected verification.

CI failure, startup failure, missing logs, unavailable reviewer, quota failure,
or absent required evidence is not PASS. Record CI_UNAVAILABLE or
REVIEW_UNAVAILABLE only when evidence supports that classification; otherwise
record failure or unknown. Local success does not replace required hosted
checks. Existing owner exception rules remain controlling; a documented
exception is not a pass and never waives non-waivable gates.

## 4. State and publication rules

IN_PROGRESS: work underway.
SELF_AUDIT_FAILED: author found unresolved defects.
BLOCKED: mandatory dependency, evidence, permission or check is missing.
IMPLEMENTED: change exists; acceptance is pending.
SELF_VERIFIED: all applicable author checks passed; independent review pending.
INDEPENDENT_PASS: non-author reviewer approved exact head; other gates may remain.
MERGE_READY: all existing mandatory acceptance gates and owner approval satisfied.
MERGED: merge independently confirmed on target branch.

A draft PR, progress report, or blocker report may be published before
certification if clearly labeled. A completion or merge-ready claim MUST NOT
be published when its gates are unmet. Never suppress material failures,
urgent safety issues or genuine owner decisions to satisfy a reporting rule.
Do not equate an accepted plan, a push, or a closed unmerged PR with delivery.
Keep routine intermediate correction loops internal within approved scope.
After three unsuccessful correction cycles on a work order, stop and escalate
with findings, exact evidence, remaining scope and options. Do not reset the
counter by renaming the task or branch. Earlier escalation is required for
security, permission, scope or resource blockers.

## 5. Required owner-facing report / certificate fields

- Work order ID, repository, candidate/base SHA (or immutable research artifact
  ID), author identity, policy version and acceptance-criteria digest.
- Authorization and allowed paths; actual changed paths.
- Requirement IDs with satisfied/outstanding status and evidence links.
- Pass A/B/C outcomes and remaining findings.
- Test/check name, command, exact tested SHA, environment, execution UTC,
  exit code, counts, artifact reference and digest where available.
- Independent reviewer identity, role, exact reviewed SHA, verdict and
  finding dispositions; unavailable evidence labeled explicitly.
- Current state, blockers, exclusions, owner decisions and next safe action.
- For conversational answers without a repo artifact, cite the relevant
  sources or tool results and state verification limitations; no invented SHA.

No secrets, personal data or private reasoning in certificates. Hashes provide
integrity, not proof of truthful execution or authenticated reviewer identity.

## 6. Proposed enforcement (separate owner-approved implementation)

Integrate with existing audit, handover, controller and publication mechanisms;
do not create a competing orchestration framework. Inspect existing validators
and schemas before proposing changes. Candidate certificates should bind the
work order, acceptance digest, base/head SHA, artifact hashes, check evidence
and authenticated reviewer identity. Trusted controller/publisher validates
these independently, rejects missing or stale evidence and prevents
self-certification, replay, forged identities and publication races. Worker
self-attestation alone cannot satisfy independent gates. Maintain owner-only
merge authority and fail closed if required checks or evidence are unavailable.

Before activation, require adversarial tests for fabricated PASS, stale SHA,
wrong reviewer, missing findings, changed artifacts, skipped checks, invalid
waiver, unauthorized scope and report/merge race. Require independent audit and
separate owner approval. This documentation PR implements no validator, runner,
workflow, branch protection, provider call, or automatic enforcement.

## 7. Owner acceptance checklist

- Universal applicability, including humans and GPT, and compatibility with
  existing governance.
- Three distinct review passes and non-author certification.
- Explicit evidence/status vocabulary and no premature completion.
- Exact-head invalidation, failure handling and bounded correction loops.
- No change to current safety, authorization or merge boundaries.
- Separate implementation and activation decisions.
