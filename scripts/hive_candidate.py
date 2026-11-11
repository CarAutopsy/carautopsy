"""Deterministic schema, identity, and evidence gates for Hive drafts."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "vehicle-variant.schema.json"
MAX_EVIDENCE_SOURCES = 10
MAX_EXCERPT_CHARS = 20_000
MAX_TOTAL_EXCERPT_CHARS = 60_000
MAX_SOURCE_ID_CHARS = 128
MAX_URL_CHARS = 2_048
MAX_RETRIEVED_AT_CHARS = 64
MAX_TOTAL_EVIDENCE_JSON_CHARS = 70_000
MAX_CANDIDATE_JSON_CHARS = 1_000_000
MAX_CANDIDATE_DEPTH = 64
TECHNICAL_CLAIM_ROOTS = ("identity", "performance", "energy", "dimensions", "emissions", "offers", "warranty", "registration")
NON_CLAIM_OFFER_FIELDS = {"offer_id", "country", "currency"}
NON_CLAIM_IDENTITY_FIELDS = {"make", "model"}
MAX_CLAIM_QUOTE_CHARS = 2_000
MAX_CLAIM_BINDINGS = 200


class CandidateRejected(ValueError):
    """Raised when a generated vehicle draft fails a deterministic gate."""


def _reject_non_finite(value: str):
    """Reject JavaScript-style non-finite constants during JSON decoding."""
    raise CandidateRejected(f"non-finite JSON number is forbidden: {value}")


def parse_candidate_json(raw: str) -> dict[str, Any]:
    """Decode exactly one JSON object and reject non-finite numbers."""
    if not isinstance(raw, str):
        raise CandidateRejected("candidate response must be text")
    if len(raw) > MAX_CANDIDATE_JSON_CHARS:
        raise CandidateRejected("candidate response exceeds the size limit")
    try:
        value = json.loads(raw, parse_constant=_reject_non_finite)
    except CandidateRejected:
        raise
    except (json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise CandidateRejected("candidate response is not valid JSON or exceeds the nesting limit") from exc
    _check_json_limits(value)
    if not isinstance(value, dict):
        raise CandidateRejected("candidate must be a JSON object")
    return value


def _check_json_limits(value: Any) -> None:
    """Reject non-finite numbers, excessive nesting, and unbounded JSON objects."""
    import math

    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_CANDIDATE_DEPTH:
            raise CandidateRejected("candidate exceeds the maximum nesting depth")
        if isinstance(current, float) and not math.isfinite(current):
            raise CandidateRejected("candidate contains a non-finite number")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for pair in current.items() for item in pair)
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _bounded_json_size(value: Any, label: str) -> int:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CandidateRejected(f"{label} is not safely serializable JSON") from exc
    size = len(encoded.encode("utf-8"))
    if size > MAX_CANDIDATE_JSON_CHARS:
        raise CandidateRejected(f"{label} exceeds the size limit")
    _check_json_limits(value)
    return size


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
        url = item["url"].strip()
        retrieved_at = item["retrieved_at"].strip()
        if len(source_id) > MAX_SOURCE_ID_CHARS:
            raise CandidateRejected(f"evidence source_id exceeds {MAX_SOURCE_ID_CHARS} characters")
        if len(url) > MAX_URL_CHARS:
            raise CandidateRejected(f"evidence URL exceeds {MAX_URL_CHARS} characters")
        if len(retrieved_at) > MAX_RETRIEVED_AT_CHARS:
            raise CandidateRejected(
                f"evidence retrieved_at exceeds {MAX_RETRIEVED_AT_CHARS} characters"
            )
        if source_id in seen_ids:
            raise CandidateRejected(f"duplicate evidence source_id: {source_id}")
        seen_ids.add(source_id)
        excerpt = item["text"]
        if len(excerpt) > MAX_EXCERPT_CHARS:
            raise CandidateRejected(f"evidence excerpt exceeds {MAX_EXCERPT_CHARS} characters")
        total_chars += len(excerpt)
        normalized.append({
            "source_id": source_id,
            "url": url,
            "retrieved_at": retrieved_at,
            "text": excerpt.strip(),
        })
    if total_chars > MAX_TOTAL_EXCERPT_CHARS:
        raise CandidateRejected(
            f"combined evidence excerpts exceed {MAX_TOTAL_EXCERPT_CHARS} characters"
        )
    try:
        serialized_size = len(json.dumps(
            normalized, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CandidateRejected("evidence bundle is not safely serializable") from exc
    if serialized_size > MAX_TOTAL_EVIDENCE_JSON_CHARS:
        raise CandidateRejected(
            f"serialized evidence bundle exceeds {MAX_TOTAL_EVIDENCE_JSON_CHARS} bytes"
        )
    return normalized


def _technical_claim_paths(candidate: dict[str, Any]) -> set[str]:
    """Return paths for non-null canonical technical/registration/price claim values."""
    paths: set[str] = set()

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if path == "offers" and key in NON_CLAIM_OFFER_FIELDS:
                    continue
                if path == "identity" and key in NON_CLAIM_IDENTITY_FIELDS:
                    continue
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif value is not None and (not isinstance(value, str) or value.strip()):
            paths.add(path)
            if len(paths) > MAX_CLAIM_BINDINGS:
                raise CandidateRejected("candidate contains too many technical claims")

    for root in TECHNICAL_CLAIM_ROOTS:
        if root in candidate:
            walk(candidate[root], root)
    return paths


def _locator_text(source_text: str, locator: str) -> str | None:
    """Return only the text belonging to one explicit document/page marker."""
    markers = list(re.finditer(r"(?m)^\[([A-Za-z0-9:_-]+)\]\s*$", source_text))
    for index, match in enumerate(markers):
        if match.group(1) != locator:
            continue
        end = markers[index + 1].start() if index + 1 < len(markers) else len(source_text)
        return source_text[match.end():end].strip()
    return None


def _validate_claim_evidence(
    candidate: dict[str, Any],
    evidence: list[dict[str, str]],
    provenance: dict[str, Any],
) -> None:
    """Require each non-null technical claim to cite an exact supplied text span."""
    required_paths = _technical_claim_paths(candidate)
    bindings = provenance.get("claim_evidence")
    if not required_paths:
        if bindings not in (None, []):
            if not isinstance(bindings, list):
                raise CandidateRejected("claim_evidence must be an array")
        return
    if not isinstance(bindings, list) or not bindings:
        raise CandidateRejected("every non-null technical claim requires claim_evidence")
    evidence_by_id = {item["source_id"]: item for item in evidence}
    declared_ids = {
        item.get("source_id") for item in (provenance.get("sources") or [])
        if isinstance(item, dict)
    }
    covered: set[str] = set()
    seen: set[tuple[str, str, str]] = set()
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            raise CandidateRejected(f"claim evidence item {index} must be an object")
        claim_path = binding.get("claim_path")
        source_id = binding.get("source_id")
        locator = binding.get("locator")
        quote = binding.get("quote")
        if not isinstance(claim_path, str) or claim_path not in required_paths:
            raise CandidateRejected(f"claim evidence item {index} references an unknown claim path")
        if not isinstance(source_id, str) or source_id not in evidence_by_id or source_id not in declared_ids:
            raise CandidateRejected(f"claim evidence item {index} references an unknown or undeclared source")
        if not isinstance(locator, str) or not locator.strip() or len(locator) > 128:
            raise CandidateRejected(f"claim evidence item {index} has an invalid locator")
        if not isinstance(quote, str) or not quote.strip() or len(quote) > MAX_CLAIM_QUOTE_CHARS:
            raise CandidateRejected(f"claim evidence item {index} has an invalid quote")
        source_text = evidence_by_id[source_id]["text"]
        located_text = _locator_text(source_text, locator)
        if located_text is None:
            raise CandidateRejected(f"claim evidence locator {locator} is not present in source text")
        if quote not in located_text:
            raise CandidateRejected("claim evidence quote is not an exact span at the stated locator")
        identity = (claim_path, source_id, quote)
        if identity in seen:
            raise CandidateRejected("duplicate claim evidence binding")
        seen.add(identity)
        covered.add(claim_path)
    missing = sorted(required_paths - covered)
    if missing:
        raise CandidateRejected("technical claims lack evidence bindings: " + ", ".join(missing[:10]))


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

    _bounded_json_size(candidate, "candidate")
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
    declared_ids = set()
    for index, source in enumerate(declared_sources):
        if not isinstance(source, dict):
            raise CandidateRejected(f"candidate provenance source {index} must be an object")
        source_id = source.get("source_id")
        url = source.get("url")
        if not isinstance(source_id, str) or source_id not in evidence_by_id:
            raise CandidateRejected(f"candidate provenance source {index} is not in the evidence bundle")
        if source_id in declared_ids:
            raise CandidateRejected("candidate provenance contains a duplicate source_id")
        declared_ids.add(source_id)
        if url != evidence_by_id[source_id]:
            raise CandidateRejected(f"candidate provenance URL does not match evidence source {source_id}")

    _validate_claim_evidence(result, sources, provenance)

    # These fields are pipeline-owned, never trusted from model output.
    provenance["confidence"] = "low"
    provenance["reviewed_by"] = None
    extensions = result.get("extensions")
    if isinstance(extensions, dict):
        extensions.pop("hive", None)

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

    _bounded_json_size(result, "candidate")
    return result
