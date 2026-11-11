"""Deterministic schema, identity, and evidence gates for Hive drafts."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "vehicle-variant.schema.json"
MAX_EVIDENCE_SOURCES = 10
MAX_EXCERPT_CHARS = 20_000
MAX_TOTAL_EXCERPT_CHARS = 60_000


class CandidateRejected(ValueError):
    """Raised when a generated vehicle draft fails a deterministic gate."""


def _reject_non_finite(value: str):
    """Reject JavaScript-style non-finite constants during JSON decoding."""
    raise CandidateRejected(f"non-finite JSON number is forbidden: {value}")


def parse_candidate_json(raw: str) -> dict[str, Any]:
    """Decode exactly one JSON object and reject non-finite numbers."""
    if not isinstance(raw, str):
        raise CandidateRejected("candidate response must be text")
    try:
        value = json.loads(raw, parse_constant=_reject_non_finite)
    except CandidateRejected:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise CandidateRejected("candidate response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise CandidateRejected("candidate must be a JSON object")
    return value


def validate_evidence_bundle(evidence: Any) -> list[dict[str, str]]:
    """Validate a bounded, non-empty set of uniquely identified source excerpts."""
    if not isinstance(evidence, list) or not evidence:
        raise CandidateRejected("evidence bundle must be a non-empty array")
    if len(evidence) > MAX_EVIDENCE_SOURCES:
        raise CandidateRejected("evidence bundle exceeds the source-count limit")

    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    total_chars = 0
    required = ("source_id", "url", "retrieved_at", "text")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise CandidateRejected(f"evidence item {index} must be an object")
        for key in required:
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise CandidateRejected(f"evidence item {index} is missing non-empty {key}")
        source_id = item["source_id"].strip()
        if source_id in seen_ids:
            raise CandidateRejected(f"duplicate evidence source_id: {source_id}")
        seen_ids.add(source_id)
        excerpt = item["text"]
        if len(excerpt) > MAX_EXCERPT_CHARS:
            raise CandidateRejected(f"evidence excerpt exceeds {MAX_EXCERPT_CHARS} characters")
        total_chars += len(excerpt)
        normalized.append({key: item[key].strip() for key in required})
    if total_chars > MAX_TOTAL_EXCERPT_CHARS:
        raise CandidateRejected(
            f"combined evidence excerpts exceed {MAX_TOTAL_EXCERPT_CHARS} characters"
        )
    return normalized


def validate_candidate(
    candidate: Any,
    task: dict[str, Any],
    evidence: Any,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    """Return a normalized copy only when schema, reserved identity, and evidence pass."""
    if not isinstance(candidate, dict):
        raise CandidateRejected("candidate must be a JSON object")
    if not isinstance(task, dict):
        raise CandidateRejected("reserved task must be an object")
    for key in ("variant_id", "make", "model"):
        if not isinstance(task.get(key), str) or not task[key].strip():
            raise CandidateRejected(f"reserved task is missing {key}")

    result = copy.deepcopy(candidate)
    identity = result.get("identity")
    if result.get("variant_id") != task["variant_id"]:
        raise CandidateRejected("candidate variant_id does not match reserved task")
    if not isinstance(identity, dict):
        raise CandidateRejected("candidate identity must be an object")
    if identity.get("make") != task["make"]:
        raise CandidateRejected("candidate identity.make does not match reserved task")
    if identity.get("model") != task["model"]:
        raise CandidateRejected("candidate identity.model does not match reserved task")

    sources = validate_evidence_bundle(evidence)
    evidence_by_id = {item["source_id"]: item["url"] for item in sources}
    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        raise CandidateRejected("candidate provenance must be an object")
    declared_sources = provenance.get("sources")
    if not isinstance(declared_sources, list) or not declared_sources:
        raise CandidateRejected("candidate must cite at least one supplied evidence source")
    for index, source in enumerate(declared_sources):
        if not isinstance(source, dict):
            raise CandidateRejected(f"candidate provenance source {index} must be an object")
        source_id = source.get("source_id")
        url = source.get("url")
        if not isinstance(source_id, str) or source_id not in evidence_by_id:
            raise CandidateRejected(f"candidate provenance source {index} is not in the evidence bundle")
        if url != evidence_by_id[source_id]:
            raise CandidateRejected(f"candidate provenance URL does not match evidence source {source_id}")

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(result))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise CandidateRejected("repository vehicle schema could not be loaded") from exc
    if errors:
        error = sorted(errors, key=lambda item: list(map(str, item.absolute_path)))[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise CandidateRejected(f"schema violation at {location}: {error.message}")

    # These fields are pipeline-owned, never trusted from model output.
    provenance["confidence"] = "low"
    provenance["reviewed_by"] = None
    extensions = result.get("extensions")
    if isinstance(extensions, dict):
        extensions.pop("hive", None)

    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CandidateRejected("candidate cannot be safely serialized as finite JSON") from exc
    return result
