# Next Actions

**Last reconciled:** 2026-11-12  
**Authoritative sequence:** [ROADMAP.md](ROADMAP.md)

## Immediate

1. Review and merge the documentation-only roadmap reconciliation PR.
2. Reconcile issue #44 with the prompt/candidate helper implementation already merged in PR #49; retain only genuinely outstanding acceptance work.
3. Keep issue #37 open as the primary runtime integration and source-provenance workstream.
4. Keep issue #47 open until a genuinely independent human/external audit is recorded against the exact reviewed SHA.

## Next implementation increment

1. Inspect the actual exported APIs and side effects in `scripts/hive_prompts.py`, `scripts/hive_candidate.py`, `scripts/hive_evidence.py`, and `scripts/hive_source_policy.py`.
2. Create one testable orchestration seam: reserved task → owner-approved evidence retrieval → researcher prompt → candidate parse → deterministic validation → validated candidate/evidence pair.
3. Wire the seam before all auditor calls in `scripts/autonomous_pipeline.py`.
4. Route retries, restarts, existing proposals, and state branches through the same gate.
5. Add tests proving rejected candidates never reach auditors and failure/pause paths cause zero provider calls and zero durable state mutation.

## Required verification

- Full Python unit suite.
- Catalog validation.
- Recursive compilation of scripts and tests.
- Repository Audit and relevant GitHub Actions checks on the exact final commit SHA.
- Independent external security review before any activation decision.

## Do not do yet

- Do not populate `data-connectors/approved-source-hosts.json`.
- Do not set `VERIFIED_RETRIEVAL_AVAILABLE = True` or remove `HIVE_RESEARCH_PAUSED`.
- Do not perform live OEM retrieval or paid provider calls.
- Do not dispatch or automatically retry the 23 vehicle queue entries.
- Do not treat previous failed candidate records as verified data.
