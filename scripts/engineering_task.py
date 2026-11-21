"""Pure, offline foundation for a future owner-gated engineering agent.

No provider call, repository write, PR creation or scheduling is performed by
this module. It only validates task contracts, computes immutable snapshots,
bounds patches, parses audit results and emits read-only proposals. Activation
remains a separate owner decision (issue #114 Phase 2 design).
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any

from hive_audit import concise_audit_verdict
from hive_outcomes import (
    MANUAL_REVIEW_REQUIRED,
    OUTCOME_CODES,
    PROVIDER_TRANSPORT_FAILURE,
    PROVENANCE_REJECTION,
    RESPONSE_FORMAT_FAILURE,
    VEHICLE_QUALITY_REJECTION,
)
FAILURE_CODES = frozenset({
    PROVIDER_TRANSPORT_FAILURE,
    RESPONSE_FORMAT_FAILURE,
    PROVENANCE_REJECTION,
    VEHICLE_QUALITY_REJECTION,
})


class TaskContractError(ValueError):
    """Raised when an engineering task contract is malformed or unsafe."""


_TASK_ID = re.compile(r"eng-[a-z0-9][a-z0-9-]{1,63}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_PATH = re.compile(r"[A-Za-z0-9_./-]+\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
MAX_UNTRUSTED_CHARS = 8_000
PROTECTED_PATH_PREFIXES = (
    "data-connectors/",
    ".github/",
    "docs/operations/",
    "country-packs/",
    "schemas/",
    "tco-contract.json",
)
PROTECTED_PATHS = frozenset({
    "scripts/autonomous_pipeline.py",
    "scripts/hive_research_gate.py",
    "scripts/hive_source_policy.py",
    "scripts/hive_source_retrieval.py",
    "scripts/hive_source_extract.py",
    "scripts/hive_evidence.py",
    "scripts/hive_candidate.py",
    "scripts/hive_audit.py",
    "scripts/hive_orchestration.py",
    "scripts/tco_publication.py",
    "scripts/engineering_task.py",
    "scripts/hive_outcomes.py",
    "scripts/validate_tco_readiness.py",
    "scripts/tco_engine.py",
})
TASK_WRITABLE_PREFIXES = (
    "apps/web/src/",
    "tests/fixtures/",
)


def normalize_allowed_path(path: Any) -> str:
    """Return a canonical POSIX path or fail closed on ambiguous spellings."""
    if not isinstance(path, str) or not path or path.startswith("/"):
        raise TaskContractError("allowed path must be a non-empty relative path")
    candidate = path.replace("\\", "/")
    if "\x00" in candidate or any(ord(char) < 32 for char in candidate):
        raise TaskContractError("allowed path contains control characters")
    normalized = posixpath.normpath(candidate)
    if candidate != normalized:
        raise TaskContractError("allowed path is not a canonical relative path")
    parts = normalized.split("/")
    if (
        normalized in {".", ".."}
        or normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or any(part.endswith(".") or part.endswith(" ") for part in parts)
    ):
        raise TaskContractError("allowed path is not a canonical relative path")
    return normalized


def validate_task_contract(contract: Any) -> dict[str, Any]:
    """Validate and normalize a trusted engineering task contract."""
    if not isinstance(contract, dict):
        raise TaskContractError("task contract must be an object")
    task_id = contract.get("task_id")
    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise TaskContractError("task_id must be an eng- slug")
    if contract.get("repository") != "CarAutopsy/carautopsy" or _REPOSITORY.fullmatch(
        str(contract.get("repository", ""))
    ) is None:
        raise TaskContractError("repository must be the exact target repository")
    base_sha = contract.get("base_sha")
    if not isinstance(base_sha, str) or _SHA1.fullmatch(base_sha) is None:
        raise TaskContractError("base_sha must be a 40-character commit SHA")

    allowed_paths = contract.get("allowed_paths")
    if not isinstance(allowed_paths, list) or not allowed_paths or len(allowed_paths) > 100:
        raise TaskContractError("allowed_paths must be a bounded non-empty list")
    normalized_paths = []
    for path in allowed_paths:
        normalized = normalize_allowed_path(path)
        if _SAFE_PATH.fullmatch(normalized) is None:
            raise TaskContractError("allowed path is not a safe relative path")
        folded = normalized.casefold()
        if folded in {item.casefold() for item in PROTECTED_PATHS} or any(
            folded.startswith(prefix.casefold()) for prefix in PROTECTED_PATH_PREFIXES
        ):
            raise TaskContractError(f"protected path cannot be an engineering task target: {normalized}")
        if not any(folded.startswith(prefix.casefold()) for prefix in TASK_WRITABLE_PREFIXES):
            raise TaskContractError(f"path is outside the engineering task allowlist: {normalized}")
        normalized_paths.append(normalized)
    if len({item.casefold() for item in normalized_paths}) != len(normalized_paths):
        raise TaskContractError("duplicate allowed path")

    for field in ("goal", "acceptance_criteria"):
        value = contract.get(field)
        if field == "goal":
            if not isinstance(value, str) or not value.strip():
                raise TaskContractError("goal must be a non-empty string")
        else:
            if (
                not isinstance(value, list) or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)
                or len(value) > 50
            ):
                raise TaskContractError("acceptance_criteria must be a bounded non-empty string list")

    numeric_limits = {
        "max_patch_bytes": 1_000_000,
        "max_files_touched": 50,
        "timeout_seconds": 3_600,
        "max_provider_calls": 20,
        "max_spend_units": 0,
    }
    limits = {}
    for field, ceiling in numeric_limits.items():
        value = contract.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > ceiling:
            raise TaskContractError(f"{field} must be an integer in 0..{ceiling}")
        limits[field] = value
    if limits["max_spend_units"] != 0:
        raise TaskContractError("max_spend_units must remain zero until owner authorization")

    dependencies = contract.get("dependencies", [])
    if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
        raise TaskContractError("dependencies must be a string list")
    if contract.get("requires_owner_approval") is not True:
        raise TaskContractError("owner approval must be required")
    source_ref = contract.get("source_ref")
    if source_ref is not None and (not isinstance(source_ref, str) or len(source_ref) > 300):
        raise TaskContractError("source_ref must be a bounded string")

    return {
        "task_id": task_id,
        "repository": contract["repository"],
        "base_sha": base_sha,
        "allowed_paths": sorted(normalized_paths),
        "goal": contract["goal"].strip(),
        "acceptance_criteria": [item.strip() for item in contract["acceptance_criteria"]],
        **limits,
        "dependencies": sorted(set(dependencies)),
        "requires_owner_approval": True,
        "source_ref": source_ref,
    }


def attach_untrusted_text(contract: dict[str, Any], text: Any) -> dict[str, Any]:
    """Attach issue text as inert evidence; never let it set contract fields."""
    if not isinstance(text, str):
        raise TaskContractError("untrusted text must be a string")
    result = dict(contract)
    result["untrusted_text"] = text[:MAX_UNTRUSTED_CHARS]
    result["untrusted_text_truncated"] = len(text) > MAX_UNTRUSTED_CHARS
    return result


def snapshot_manifest(root: Path, allowed_paths: list[str]) -> dict[str, str]:
    """Hash the exact bytes of each allow-listed input file."""
    assert_no_symlinks(root, allowed_paths)
    manifest = {}
    for relative in sorted(allowed_paths):
        path = Path(root) / relative
        if not path.is_file():
            raise TaskContractError(f"snapshot input is missing: {relative}")
        manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def assert_patch_within_limits(contract: dict[str, Any], patch_sizes: dict[str, int]) -> None:
    """Reject patches that exceed path, count or byte limits."""
    if not isinstance(patch_sizes, dict):
        raise TaskContractError("patch sizes must be a mapping")
    allowed = set(contract["allowed_paths"])
    for path, size in patch_sizes.items():
        if path not in allowed:
            raise TaskContractError(f"patch touches a disallowed path: {path}")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise TaskContractError("patch size must be a non-negative integer")
    if len(patch_sizes) > contract["max_files_touched"]:
        raise TaskContractError("patch file count exceeds the task limit")
    if sum(patch_sizes.values()) > contract["max_patch_bytes"]:
        raise TaskContractError("patch byte count exceeds the task limit")


def parse_audit_quorum(
    audits: list[dict[str, Any]], *, bundle_sha256: str, base_sha: str
) -> dict[str, Any]:
    """Require two distinct vendors bound to the same exact bundle and SHA."""
    if not isinstance(bundle_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", bundle_sha256):
        return {"accepted": False, "reason": "bundle digest is invalid"}
    if not isinstance(base_sha, str) or _SHA1.fullmatch(base_sha) is None:
        return {"accepted": False, "reason": "base SHA is invalid"}
    if not isinstance(audits, list) or len(audits) != 2 or not all(isinstance(item, dict) for item in audits):
        return {"accepted": False, "reason": "audit quorum must contain exactly two objects"}
    vendors = [str(item.get("vendor", "")).strip().casefold() for item in audits]
    if len(set(vendors)) != 2 or not all(vendors):
        return {"accepted": False, "reason": "audit vendors must be distinct and named"}
    for item in audits:
        if item.get("bundle_sha256") != bundle_sha256 or item.get("base_sha") != base_sha:
            return {"accepted": False, "reason": "audit verdict is not bound to this bundle and SHA"}
    verdicts = [concise_audit_verdict(item.get("verdict")) for item in audits]
    if any(verdict != "PASS" for verdict in verdicts):
        return {"accepted": False, "reason": "both verdicts must be exact PASS tokens"}
    return {
        "accepted": True,
        "vendors": sorted(vendors),
        "verdicts": verdicts,
        "bundle_sha256": bundle_sha256,
        "base_sha": base_sha,
    }


def snapshot_digest(manifest: dict[str, str]) -> str:
    """Stable digest of an immutable snapshot manifest."""
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def next_retry_count(contract: dict[str, Any], previous: Any) -> int:
    """Return a bounded retry count; invalid inputs fail closed at the ceiling."""
    ceiling = contract["max_provider_calls"]
    if isinstance(previous, bool) or not isinstance(previous, int) or previous < 0 or previous > ceiling:
        return ceiling
    return min(previous + 1, ceiling)


def assert_no_symlinks(root: Path, allowed_paths: list[str]) -> None:
    """Reject symlinks in any path component; never follow them into a snapshot."""
    base = Path(root).resolve()
    for relative in sorted(allowed_paths):
        candidate = Path(root) / relative
        walked = Path(root)
        for part in Path(relative).parts:
            walked = walked / part
            if walked.is_symlink():
                raise TaskContractError(f"symlink in snapshot path: {relative}")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise TaskContractError(f"snapshot path cannot be resolved: {relative}") from exc
        if base not in resolved.parents and resolved != base:
            raise TaskContractError(f"snapshot path escapes the repository root: {relative}")


def reserve_task(contract: dict[str, Any], state: Any) -> dict[str, Any]:
    """Create or return an identical reservation; conflicts fail closed."""
    task_id = contract["task_id"]
    base_sha = contract["base_sha"]
    if state is not None:
        if not isinstance(state, dict):
            raise TaskContractError("reservation state must be an object")
        active = state.get("reservation")
        if isinstance(active, dict) and active.get("task_id") == task_id:
            if active.get("base_sha") != base_sha:
                raise TaskContractError("stale reservation for a different base SHA")
            return dict(active)
    digest = hashlib.sha256(f"{task_id}:{base_sha}".encode("utf-8")).hexdigest()
    return {
        "reservation_id": digest[:24],
        "task_id": task_id,
        "base_sha": base_sha,
        "status": "reserved",
        "requires_owner_approval": True,
    }


def classify_failure(code: Any) -> str:
    """Map a structured failure code to the allowlist; free text is never trusted."""
    if isinstance(code, str) and code in FAILURE_CODES:
        return code
    return MANUAL_REVIEW_REQUIRED


def task_outcome(reservation: dict[str, Any], bundle: dict[str, Any], code: str) -> dict[str, Any]:
    """Return a deterministic, idempotent outcome record."""
    if code not in OUTCOME_CODES:
        raise TaskContractError("outcome code is not allowlisted")
    if not isinstance(reservation, dict) or not isinstance(bundle, dict):
        raise TaskContractError("reservation and bundle must be objects")
    if not isinstance(bundle.get("bundle_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", bundle["bundle_sha256"]
    ):
        raise TaskContractError("task outcome requires a bundle SHA-256 digest")
    key_source = ":".join([
        str(reservation.get("reservation_id", "")),
        str(bundle.get("bundle_sha256", "")),
        code,
    ])
    return {
        "reservation_id": reservation.get("reservation_id"),
        "bundle_sha256": bundle.get("bundle_sha256"),
        "code": code,
        "requires_owner_approval": True,
        "publication_enabled": False,
        "idempotency_key": hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:24],
    }


def draft_pull_request_proposal(contract: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    """Return an owner-gated draft-PR proposal; never creates or publishes one."""
    return {
        "schema_version": 1,
        "task_id": contract["task_id"],
        "base_sha": contract["base_sha"],
        "bundle_sha256": bundle.get("bundle_sha256"),
        "mode": "proposal-only",
        "target": "draft-pull-request",
        "draft_pr_created": False,
        "publication_enabled": False,
        "requires_owner_approval": True,
    }


def build_verification_bundle(
    contract: dict[str, Any],
    manifest: dict[str, str],
    audit_result: dict[str, Any],
    *,
    owner_approved: bool = False,
) -> dict[str, Any]:
    """Emit a deterministic, read-only bundle; never authorizes execution."""
    if not isinstance(manifest, dict) or not isinstance(audit_result, dict):
        raise TaskContractError("manifest and audit result must be objects")
    expected_digest = snapshot_digest(manifest)
    if audit_result.get("accepted") is not True:
        raise TaskContractError("audit quorum must be accepted before verification")
    if audit_result.get("bundle_sha256") != expected_digest:
        raise TaskContractError("audit quorum is not bound to this snapshot digest")
    if audit_result.get("base_sha") != contract["base_sha"]:
        raise TaskContractError("audit quorum is not bound to this base SHA")
    payload = {
        "schema_version": 1,
        "task_id": contract["task_id"],
        "base_sha": contract["base_sha"],
        "snapshot": manifest,
        "audit": audit_result,
        "requires_owner_approval": True,
        "owner_approved": bool(owner_approved),
        "execution_enabled": False,
        "draft_pr_created": False,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["bundle_sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return payload
