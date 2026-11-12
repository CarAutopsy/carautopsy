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
    from .hive_candidate import CandidateRejected, parse_candidate_json, validate_candidate
    from .hive_prompts import build_auditor_prompt, build_researcher_prompt
    from .hive_audit import concise_audit_verdict
except ImportError:  # pragma: no cover - exercised by direct script execution.
    from hive_evidence import EvidenceRetrievalRejected, retrieve_approved_evidence
    from hive_candidate import CandidateRejected, parse_candidate_json, validate_candidate
    from hive_prompts import build_auditor_prompt, build_researcher_prompt
    from hive_audit import concise_audit_verdict


class OrchestrationRejected(ValueError):
    """Raised when the research path cannot safely proceed to an auditor."""

    def __init__(self, message: str, *, code: str = "provenance_rejection"):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class OrchestrationResult:
    """Validated research artifacts; contains no raw source bytes or secrets."""

    candidate: dict[str, Any]
    evidence: list[dict[str, str]]
    research_task: dict[str, Any]
    orchestration_id: str
    retrieved_at: str
    source_ids: tuple[str, ...]
    researcher_provider: str | None = None
    researcher_vendor: str | None = None


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
    try:
        return parse_candidate_json(raw)
    except CandidateRejected as exc:
        raise OrchestrationRejected(
            "researcher response is not one bounded JSON object",
            code="response_format_failure",
        ) from exc


def prepare_validated_research_task(
    *,
    reserved_task: dict[str, Any],
    schema: dict[str, Any],
    config_path: Path | None = None,
    config: dict[str, Any] | None = None,
    fetcher: Callable = None,
    extractor: Callable = None,
    researcher: Callable | None = None,
    research_context: dict[str, Any] | None = None,
    today: date | None = None,
) -> OrchestrationResult:
    """Run the mandatory pre-auditor research sequence and return validated artifacts.

    This function never invokes an auditor. It never enables live retrieval and
    never accepts source URLs, hosts, or policy decisions from model output.
    """
    variant_id, make, model = _reserved_identity(reserved_task)

    retrieval_args = {"variant_id": variant_id, "today": today}
    if config_path is not None:
        retrieval_args["config_path"] = config_path
    if config is not None:
        retrieval_args["config"] = config
    if fetcher is not None:
        retrieval_args["fetcher"] = fetcher
    if extractor is not None:
        retrieval_args["extractor"] = extractor
    try:
        evidence = retrieve_approved_evidence(**retrieval_args)
    except Exception as exc:
        raise OrchestrationRejected(
            "source retrieval or policy check failed closed",
            code="retrieval_unavailable",
        ) from exc

    if not evidence:
        raise OrchestrationRejected("no bounded evidence was produced")

    research_task = {
        "variant_id": variant_id,
        "make": make,
        "model": model,
    }
    if research_context:
        # Only allow bounded, pipeline-derived categories; never forward raw
        # provider feedback or previous candidate text into a new prompt.
        categories = research_context.get("previous_audit_categories", [])
        if isinstance(categories, list):
            allowed = {
                "provenance_evidence", "unit_mismatch", "schema_compliance",
                "numeric_consistency", "technical_specification",
                "unspecified_quality_defect",
            }
            research_task["previous_audit_categories"] = sorted(
                {item for item in categories if isinstance(item, str) and item in allowed}
            )
    if researcher is None:
        raise OrchestrationRejected("researcher callback is required")
    try:
        prompt = build_researcher_prompt(research_task, schema, evidence)
        researcher_response = researcher(prompt)
    except Exception as exc:
        failure_code = getattr(exc, "failure_code", "provider_transport_failure")
        if failure_code not in {"provider_transport_failure", "response_format_failure"}:
            failure_code = "provider_transport_failure"
        raise OrchestrationRejected(
            "researcher invocation failed closed", code=failure_code
        ) from exc

    researcher_provider = None
    researcher_vendor = None
    if isinstance(researcher_response, tuple):
        if len(researcher_response) != 4:
            raise OrchestrationRejected(
                "researcher response metadata is malformed",
                code="response_format_failure",
            )
        raw_response, researcher_provider, researcher_vendor, failure_code = researcher_response
        if not isinstance(raw_response, str) or not raw_response.strip():
            safe_code = failure_code if failure_code in {
                "provider_transport_failure", "response_format_failure"
            } else "provider_transport_failure"
            raise OrchestrationRejected(
                "researcher provider returned no usable response", code=safe_code
            )
    else:
        raw_response = researcher_response

    candidate = _parse_researcher_response(raw_response)
    try:
        validated = validate_candidate(candidate, research_task, evidence)
    except (CandidateRejected, ValueError) as exc:
        raise OrchestrationRejected(
            "candidate failed deterministic validation", code="provenance_rejection"
        ) from exc

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
        researcher_provider=researcher_provider,
        researcher_vendor=researcher_vendor,
    )



def audit_validated_research_task(
    result: OrchestrationResult,
    *,
    schema: dict[str, Any],
    researcher_vendor: str | None,
    auditor: Callable,
    auditor_vendors: tuple[str, ...] = ("deepseek", "google", "qwen"),
) -> list[dict[str, str]]:
    """Audit only a validated result; both vendors receive the same prompt string."""
    if not isinstance(result, OrchestrationResult):
        raise OrchestrationRejected("auditor requires a validated orchestration result")
    if researcher_vendor not in auditor_vendors:
        raise OrchestrationRejected(
            "researcher vendor is not in the independent vendor set",
            code="response_format_failure",
        )
    selected = [vendor for vendor in auditor_vendors if vendor != researcher_vendor]
    if len(selected) < 2:
        raise OrchestrationRejected(
            "two independent auditor vendors are not available",
            code="response_format_failure",
        )
    prompt = build_auditor_prompt(result.candidate, schema, result.evidence)
    audits = []
    for vendor in selected[:2]:
        try:
            response = auditor(prompt, vendor)
        except Exception:
            response = (None, None, "provider_transport_failure")
        if not isinstance(response, tuple) or len(response) != 3:
            raw, provider, failure = None, None, "response_format_failure"
        else:
            raw, provider, failure = response
        verdict = concise_audit_verdict(raw) if isinstance(raw, str) else (
            "INVALID_AUDIT_RESPONSE" if failure == "response_format_failure" else "OFFLINE"
        )
        audits.append({
            "provider": provider or vendor,
            "vendor": vendor,
            "verdict": verdict,
        })
    return audits


def run_hive_research_and_audit(
    *,
    reserved_task: dict[str, Any],
    schema: dict[str, Any],
    researcher: Callable,
    auditor: Callable,
    researcher_vendor: str | None = None,
    config_path: Path | None = None,
    config: dict[str, Any] | None = None,
    fetcher: Callable | None = None,
    extractor: Callable | None = None,
    research_context: dict[str, Any] | None = None,
    today: date | None = None,
) -> tuple[OrchestrationResult, list[dict[str, str]]]:
    """Run retrieval, researcher, deterministic gate, then two independent audits."""
    result = prepare_validated_research_task(
        reserved_task=reserved_task,
        schema=schema,
        config_path=config_path,
        config=config,
        fetcher=fetcher,
        extractor=extractor,
        researcher=researcher,
        research_context=research_context,
        today=today,
    )
    audits = audit_validated_research_task(
        result,
        schema=schema,
        researcher_vendor=researcher_vendor or result.researcher_vendor,
        auditor=auditor,
    )
    return result, audits
