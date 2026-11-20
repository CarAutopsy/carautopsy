"""Pure, offline foundation for a future owner-gated engineering agent.

No provider call, repository write, PR creation or scheduling is performed by
this module. It only validates task contracts, computes immutable snapshots,
bounds patches, parses audit results and emits read-only proposals. Activation
remains a separate owner decision (issue #114 Phase 2 design).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from hive_audit import concise_audit_verdict


class TaskContractError(ValueError):
    """Raised when an engineering task contract is malformed or unsafe."""


_TASK_ID = re.compile(r"eng-[a-z0-9][a-z0-9-]{1,63}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_PATH = re.compile(r"[A-Za-z0-9_./-]+\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
MAX_UNTRUSTED_CHARS = 8_000


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
        if (
            not isinstance(path, str) or not path or path.startswith("/")
            or ".." in path.split("/") or _SAFE_PATH.fullmatch(path) is None
        ):
            raise TaskContractError("allowed path is not a safe relative path")
        normalized_paths.append(path)
    if len(set(normalized_paths)) != len(normalized_paths):
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


def parse_audit_quorum(audits: list[dict[str, Any]]) -> dict[str, Any]:
    """Require two distinct vendors with exact PASS verdicts."""
    if not isinstance(audits, list) or len(audits) != 2:
        return {"accepted": False, "reason": "audit quorum must contain exactly two verdicts"}
    vendors = [str(item.get("vendor", "")).strip() for item in audits if isinstance(item, dict)]
    if len(vendors) != 2 or len(set(vendors)) != 2 or not all(vendors):
        return {"accepted": False, "reason": "audit vendors must be distinct and named"}
    verdicts = [concise_audit_verdict(item.get("verdict")) for item in audits if isinstance(item, dict)]
    if any(verdict != "PASS" for verdict in verdicts):
        return {"accepted": False, "reason": "both verdicts must be exact PASS tokens"}
    return {"accepted": True, "vendors": sorted(vendors), "verdicts": verdicts}


def next_retry_count(contract: dict[str, Any], previous: Any) -> int:
    """Return a bounded retry count; invalid inputs fail closed at the ceiling."""
    ceiling = contract["max_provider_calls"]
    if isinstance(previous, bool) or not isinstance(previous, int) or previous < 0 or previous > ceiling:
        return ceiling
    return min(previous + 1, ceiling)


def build_verification_bundle(
    contract: dict[str, Any],
    manifest: dict[str, str],
    audit_result: dict[str, Any],
    *,
    owner_approved: bool = False,
) -> dict[str, Any]:
    """Emit a deterministic, read-only bundle; never authorizes execution."""
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
