# Hive issue #37 acceptance evidence

**Issue:** [#37 — Harden Hive candidate provenance validation before independent audits](https://github.com/CarAutopsy/carautopsy/issues/37)  
**Status:** Acceptance evidence record — not activation approval  
**Prepared:** 2026-11-14  
**Operating model:** one-person, zero-budget hobby project

## Purpose

This document records the implementation evidence, remaining acceptance conditions, and review boundary for issue #37. It does **not** authorize live retrieval, populate the approved-source manifest, enable paid research, dispatch the research queue, or set `VERIFIED_RETRIEVAL_AVAILABLE = True`.

The project owner remains the sole human reviewer and final authorization authority. The five AI services already used by the project provide supplementary cross-review; their findings are not independent human certification.

## Activation boundary

The following conditions remain in force:

- `VERIFIED_RETRIEVAL_AVAILABLE = False`
- `HIVE_RESEARCH_PAUSED` remains active
- `data-connectors/approved-source-hosts.json` remains empty
- No live OEM retrieval is authorized
- No paid provider call is authorized
- No research queue dispatch is authorized
- No candidate-controlled input may select or broaden an approved network destination

## Implemented acceptance evidence

| Acceptance area | Implemented by | Evidence | Status |
|---|---|---|---|
| DNS-pinned HTTPS transport | PR #50 | Isolated fail-closed retrieval primitive; validated public IP used for TCP connection; original hostname retained for TLS SNI/certificate verification; redirects rejected; bounded time/bytes/content types. | Complete for the isolated transport component. |
| Owner-controlled source policy | PR #52 | Exact host/URL source manifest, terms approval metadata, robots retrieval/parsing, bounded HTML/plain-text/PDF extraction, and owner-seeded evidence adapter. | Complete for policy/extraction/evidence components. |
| Claim-level evidence binding | PR #52 | Non-null technical/price/registration and non-reserved identity claims require exact source quote and document/page locator; duplicate source IDs and unbounded claim counts rejected. | Complete for deterministic schema/gate validation. |
| Runtime candidate gate | PR #57 | Researcher output passes schema/identity/provenance/claim-evidence validation before the two independent auditors; same auditor prompt sent to both vendors. | Complete for runtime orchestration. |
| Preflight failure isolation | PR #58 | Real pipeline subprocess test proves evidence-retrieval failure causes exit 2, no provider call, no proposal checkout, and no working-tree/ledger/state mutation. | Complete synthetic/local proof. |
| Robots denial isolation | PR #59 | Real pipeline and production robots parser prove denial produces pause, no target fetch, no provider call, no checkout, and no queue/state mutation. | Complete synthetic/local proof. |
| Target-server failure isolation | PR #60 | Real pipeline proves network/TLS failure causes fail-closed pause, zero provider calls, and no proposal/working-tree/ledger/remote/state mutation. | Complete synthetic/local proof. |
| Retry recovery | PR #61 | Two-process test proves transient researcher failure persists bounded state, then a fresh process retries through the deterministic gate and requires two independent PASS audits before publication. | Complete synthetic/local proof. |
| Abrupt restart recovery | PR #62 | SIGKILL immediately after durable `hive/state` push; fresh process restores and completes the same task. | Complete synthetic/local proof. |
| Cross-process reconciliation | PRs #63, #67, #68 | Fresh process adopts newer durable queue/failed-ledger state as a unit, preserves ordering/counters, verifies bot-written state digest, and acknowledges the exact fetched state tip. | Complete synthetic/local proof. |

## Outstanding acceptance conditions

The following must be completed before issue #37 can be considered review-complete:

1. Owner performs and records a human security review against one exact final head SHA.
2. Each of the five AI services already used by the project performs an independent security-focused review against that exact SHA.
3. Findings, disagreements, unresolved risks, residual limitations, and dispositions are recorded in `docs/operations/HIVE_EXTERNAL_SECURITY_REVIEW.md`.
4. Exact-head CI passes: Python test suite, catalog validation, provider-module compilation, and Repository Audit.
5. The owner separately reviews every proposed OEM/official hostname, exact URL, and automated-access terms before any manifest entry is added.
6. The owner explicitly authorizes activation in a separate decision after all acceptance conditions are met.

## Evidence limitations

Synthetic and local tests establish fail-closed behavior, pipeline ordering, recovery, and state-reconciliation properties. They do **not** establish:

- Live OEM robots.txt or source-terms permission
- Authenticity or factual accuracy of live source content
- Semantic relevance of an extracted quote to a technical claim
- Production readiness under real network, DNS, TLS, or OEM-site conditions
- Complete OS-level sandboxing or network isolation for parser workers

A HTTP 2xx response and `retrieved_unverified` status are never proof that a claim is supported. Quote/locator validation proves traceability, not semantic relevance or truth.

## Required review sequence

1. Pin the exact final head SHA for review.
2. Run and record full exact-head CI evidence.
3. Owner completes the human security review using the existing review template.
4. Request and record reviews from CodeRabbit, Qodo, ChatGPT, Copilot, and Perplexity.
5. Resolve or explicitly accept every material finding with rationale.
6. Record residual risks and limitations.
7. Owner separately decides whether to authorize activation.

## Stop condition

Do not enable live retrieval, populate the approved-host list, enable paid research, or set `VERIFIED_RETRIEVAL_AVAILABLE = True` as part of this documentation-only PR. Keep the research pause active until all acceptance criteria are met and the owner explicitly authorizes activation.
