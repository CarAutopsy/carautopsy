"""Zero-bypass runtime orchestration seam for Hive research tasks.

This module is intentionally not connected to live retrieval, provider calls,
or activation. It enforces the required order:

reserved task -> owner manifest -> policy/robots -> bounded retrieval ->
bounded extraction -> researcher prompt -> deterministic candidate gate.

No auditor may be invoked until this seam returns a validated candidate and
the exact same bounded evidence bundle.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:  # Support package and script-context imports.
    from .hive_evidence import EvidenceRetrievalRejected, retrieve_approved_evidence
    from .hive_candidate import CandidateRejected, validate_candidate
    from .hive_prompts import build_researcher_prompt
except ImportError:  # pragma: no cover - exercised by direct script execution.
    from hive_evidence import EvidenceRetrievalRejected, retrieve_approved_evidence
    from hive_candidate import CandidateRejected, validate_candidate
    from hive_prompts import build_researcher_prompt


class OrchestrationRejected(ValueError):
    """Raised when the research path cannot safely proceed to an auditor."""


@dataclass(frozen=True)
class OrchestrationResult:
    """Validated research artifacts; contains no raw source bytes or secrets."""

    candidate: dict[str, Any]
    evidence: list[dict[str, str]]
    research_task: dict[str, Any]
    orchestration_id: str
    retrieved_at: str
    source_ids: tuple[str, ...]


def _reserved_identity(task: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(task, dict):
        raise OrchestrationRejected("reserved task must be an object")
    variant_id = task.get("variant_id")
    make = task.get("make")
    model = task.get("model")
    for label, value in (("variant_id", variant_id), ("make", make), ("model", model)):
        if not isinstance(value, str) or not value.strip():
            raise OrchestrationRejected(f"reserved task {label} is missing or invalid")
    return variant_id, make, model


def _parse_researcher_response(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise OrchestrationRejected("researcher response must be text")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise OrchestrationRejected("researcher response is not one JSON object") from exc
    if not isinstance(value, dict):
        raise OrchestrationRejected("researcher response must be one JSON object")
    return value


def prepare_validated_research_task(
    *,
    reserved_task: dict[str, Any],
    schema: dict[str, Any],
    config_path: Path | None = None,
    config: dict[str, Any] | None = None,
    fetcher: Callable = None,
    extractor: Callable = None,
    researcher: Callable | None = None,
    today: date | None = None,
) -> OrchestrationResult:
    """Run the mandatory pre-auditor research sequence and return validated artifacts.

    This function never invokes an auditor. It never enables live retrieval and
    never accepts source URLs, hosts, or policy decisions from model output.
    """
    if fetcher is None or extractor is None:
        raise OrchestrationRejected("pinned transport and extractor are required")
    variant_id, make, model = _reserved_identity(reserved_task)

    try:
        evidence = retrieve_approved_evidence(
            variant_id=variant_id,
            config_path=config_path,
            config=config,
            fetcher=fetcher,
            extractor=extractor,
            today=today,
        )
    except (EvidenceRetrievalRejected, Exception) as exc:
        raise OrchestrationRejected("source retrieval or policy check failed closed") from exc

    if not evidence:
        raise OrchestrationRejected("no bounded evidence was produced")

    research_task = {
        "variant_id": variant_id,
        "make": make,
        "model": model,
        "schema": schema,
        "evidence": evidence,
    }
    if researcher is None:
        raise OrchestrationRejected("researcher callback is required")
    try:
        prompt = build_researcher_prompt(research_task, schema, evidence)
        raw_response = researcher(prompt)
    except Exception as exc:
        raise OrchestrationRejected("researcher invocation failed closed") from exc

    candidate = _parse_researcher_response(raw_response)
    try:
        validated = validate_candidate(candidate, research_task, evidence)
    except (CandidateRejected, ValueError) as exc:
        raise OrchestrationRejected("candidate failed deterministic validation") from exc

    # The validated candidate and evidence are returned unchanged; auditors must
    # later receive byte-for-byte equivalent inputs.
    retrieved_at = datetime.now(timezone.utc).isoformat()
    orchestration_id = hashlib.sha256(
        (variant_id + "\0" + retrieved_at + "\0" + json.dumps(evidence, sort_keys=True)).encode("utf-8")
    ).hexdigest()[:32]
    source_ids = tuple(sorted({item["source_id"] for item in evidence}))
    return OrchestrationResult(
        candidate=validated,
        evidence=evidence,
        research_task=research_task,
        orchestration_id=orchestration_id,
        retrieved_at=retrieved_at,
        source_ids=source_ids,
    )
