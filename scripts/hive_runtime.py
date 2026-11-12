"""Pipeline-facing zero-bypass runtime research path.

This wrapper routes every research entry point through the pre-auditor
orchestration seam. It never bypasses retrieval, policy, extraction, prompt
construction, or deterministic validation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

try:  # Support package and script-context imports.
    from .hive_orchestration import OrchestrationRejected, prepare_validated_research_task
except ImportError:  # pragma: no cover - exercised by direct script execution.
    from hive_orchestration import OrchestrationRejected, prepare_validated_research_task


class RuntimeResearchRejected(ValueError):
    """Raised when the runtime research path cannot safely proceed."""


class AuditorFailure(RuntimeError):
    """Raised when an independent auditor fails; distinct from provenance rejection."""


def run_hive_research_path(
    *,
    reserved_task: dict[str, Any],
    schema: dict[str, Any],
    config_path: Path | None = None,
    config: dict[str, Any] | None = None,
    fetcher: Callable = None,
    extractor: Callable = None,
    researcher: Callable | None = None,
    auditor_a: Callable | None = None,
    auditor_b: Callable | None = None,
    today=None,
) -> dict[str, Any]:
    """Run the mandatory research path; never publish automatically.

    The function returns a structured result only after both independent
    auditors return PASS. It never mutates queue, ledger, catalog, proposal,
    or audit state.
    """
    if auditor_a is None or auditor_b is None:
        raise RuntimeResearchRejected("two independent auditors are required")
    try:
        result = prepare_validated_research_task(
            reserved_task=reserved_task,
            schema=schema,
            config_path=config_path,
            config=config,
            fetcher=fetcher,
            extractor=extractor,
            researcher=researcher,
            today=today,
        )
    except OrchestrationRejected as exc:
        raise RuntimeResearchRejected("pre-auditor orchestration failed closed") from exc

    candidate = result.candidate
    evidence = result.evidence

    # Both auditors must receive byte-for-byte equivalent inputs.
    candidate_a = json.loads(json.dumps(candidate, sort_keys=True))
    evidence_a = json.loads(json.dumps(evidence, sort_keys=True))
    candidate_b = json.loads(json.dumps(candidate, sort_keys=True))
    evidence_b = json.loads(json.dumps(evidence, sort_keys=True))

    try:
        verdict_a = auditor_a(candidate_a, evidence_a)
        verdict_b = auditor_b(candidate_b, evidence_b)
    except Exception as exc:
        raise AuditorFailure("independent auditor invocation failed") from exc

    if verdict_a != "PASS" or verdict_b != "PASS":
        raise AuditorFailure("independent auditor verdict was not PASS")

    return {
        "candidate": candidate,
        "evidence": evidence,
        "orchestration_id": result.orchestration_id,
        "retrieved_at": result.retrieved_at,
        "source_ids": result.source_ids,
        "auditor_a_verdict": verdict_a,
        "auditor_b_verdict": verdict_b,
        "published": False,
    }
