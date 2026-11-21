"""Namespaced, offline retry ledger for engineering-task outcomes.

Pure helpers only: no network, ``gh``, ``git`` writes or secret access. All
keys live under the ``engineering:`` namespace so engineering retry budgets can
never collide with Hive vehicle-curation ``variant_id`` keys. This module is
not imported by any production module or workflow; activation is an owner
decision.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from engineering_task import FAILURE_CODES, TaskContractError, validate_task_contract
from hive_outcomes import AUDIT_SUCCESS, MANUAL_REVIEW_REQUIRED


class EngineeringLedgerError(ValueError):
    """Raised when ledger data or an outcome input is unsafe or malformed."""


LEDGER_NAMESPACE = "engineering"
LEDGER_SCHEMA_VERSION = 1
MAX_ENGINEERING_ATTEMPTS = 3
MAX_LEDGER_ENTRIES = 500
COUNTER_NAMES = ("attempts", "provider_attempts", "format_attempts", "verification_attempts")
ALLOWED_CODES = frozenset(FAILURE_CODES) | {AUDIT_SUCCESS, MANUAL_REVIEW_REQUIRED}

_NAMESPACE_KEY = re.compile(r"engineering:eng-[a-z0-9][a-z0-9-]{1,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ENTRY_FIELDS = frozenset({
    "task_id", "reservation_id", "digest", "code", "counters", "retryable",
    "attempt_id", "execution_enabled", "publication_enabled",
    "requires_owner_approval",
})
# Keys that would indicate a Hive vehicle-curation or legacy outcome record.
_FOREIGN_ENTRY_FIELDS = frozenset({
    "variant_id", "outcome", "candidate", "verdict", "audits", "defect_categories",
})
_CODE_COUNTER = {
    "provider_transport_failure": "provider_attempts",
    "response_format_failure": "format_attempts",
    "provenance_rejection": "verification_attempts",
    "vehicle_quality_rejection": "verification_attempts",
}


def namespaced_key(task_id: Any) -> str:
    """Return the sole valid ledger key for a task id."""
    if not isinstance(task_id, str) or _NAMESPACE_KEY.fullmatch(f"{LEDGER_NAMESPACE}:{task_id}") is None:
        raise EngineeringLedgerError("task id is not a safe engineering identifier")
    return f"{LEDGER_NAMESPACE}:{task_id}"


def empty_ledger() -> dict[str, Any]:
    """Return a new, empty, namespaced ledger."""
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "namespace": LEDGER_NAMESPACE,
        "entries": {},
    }


def load_safe_ledger(data: Any) -> dict[str, Any]:
    """Validate a ledger, rejecting foreign, legacy or malformed entries."""
    if not isinstance(data, dict):
        raise EngineeringLedgerError("ledger must be an object")
    if data.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise EngineeringLedgerError("unsupported ledger schema version")
    if data.get("namespace") != LEDGER_NAMESPACE:
        raise EngineeringLedgerError("ledger namespace is missing or foreign")
    entries = data.get("entries")
    if not isinstance(entries, dict) or len(entries) > MAX_LEDGER_ENTRIES:
        raise EngineeringLedgerError("ledger entries must be a bounded object")
    extra = set(data) - {"schema_version", "namespace", "entries"}
    if extra:
        raise EngineeringLedgerError(f"ledger contains unexpected fields: {sorted(extra)[:5]}")

    validated: dict[str, dict[str, Any]] = {}
    for key, entry in entries.items():
        if not isinstance(key, str) or _NAMESPACE_KEY.fullmatch(key) is None:
            raise EngineeringLedgerError(f"foreign or unnamespaced ledger key: {key!r}")
        if not isinstance(entry, dict):
            raise EngineeringLedgerError(f"ledger entry must be an object: {key}")
        if _FOREIGN_ENTRY_FIELDS.intersection(entry):
            raise EngineeringLedgerError(f"ledger entry looks like a Hive/legacy record: {key}")
        if set(entry) != _ENTRY_FIELDS:
            raise EngineeringLedgerError(f"ledger entry has unexpected fields: {key}")
        if entry.get("task_id") != key.split(":", 1)[1]:
            raise EngineeringLedgerError(f"ledger entry task id does not match its key: {key}")
        if entry.get("code") not in ALLOWED_CODES:
            raise EngineeringLedgerError(f"ledger entry has an untrusted code: {key}")
        if not isinstance(entry.get("reservation_id"), str) or not 1 <= len(entry["reservation_id"]) <= 80:
            raise EngineeringLedgerError(f"ledger entry has an invalid reservation id: {key}")
        if not isinstance(entry.get("digest"), str) or _DIGEST.fullmatch(entry["digest"]) is None:
            raise EngineeringLedgerError(f"ledger entry has an invalid digest: {key}")
        if not isinstance(entry.get("attempt_id"), str) or _DIGEST.fullmatch(entry["attempt_id"]) is None:
            raise EngineeringLedgerError(f"ledger entry has an invalid attempt id: {key}")
        counters = entry.get("counters")
        if not isinstance(counters, dict) or set(counters) != set(COUNTER_NAMES):
            raise EngineeringLedgerError(f"ledger entry counters are malformed: {key}")
        for name in COUNTER_NAMES:
            value = counters[name]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_ENGINEERING_ATTEMPTS:
                raise EngineeringLedgerError(f"ledger entry counter is out of bounds: {name}")
        if type(entry.get("retryable")) is not bool:
            raise EngineeringLedgerError(f"ledger entry retryable must be boolean: {key}")
        if entry.get("execution_enabled") is not False or entry.get("publication_enabled") is not False:
            raise EngineeringLedgerError(f"ledger entry must remain inert: {key}")
        if entry.get("requires_owner_approval") is not True:
            raise EngineeringLedgerError(f"ledger entry must require owner approval: {key}")
        validated[key] = copy.deepcopy(entry)

    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "namespace": LEDGER_NAMESPACE,
        "entries": validated,
    }


def _outcome_digest(bundle_or_artifact: Any) -> str:
    if not isinstance(bundle_or_artifact, dict):
        raise EngineeringLedgerError("bundle or artifact must be an object")
    candidates = [
        bundle_or_artifact.get(field)
        for field in ("bundle_sha256", "evidence_digest", "snapshot_digest")
        if field in bundle_or_artifact
    ]
    values = [value for value in candidates if isinstance(value, str) and _DIGEST.fullmatch(value)]
    if not values or len(set(values)) != 1:
        raise EngineeringLedgerError("a single valid 64-hex digest is required")
    return values[0]


def is_exhausted(entry: Any) -> bool:
    """Whether an entry has no retry budget left."""
    if not isinstance(entry, dict) or entry.get("code") not in ALLOWED_CODES:
        raise EngineeringLedgerError("entry is not a valid engineering outcome")
    code = entry["code"]
    if code == AUDIT_SUCCESS:
        return False
    if code == MANUAL_REVIEW_REQUIRED:
        return True
    counters = entry.get("counters")
    if not isinstance(counters, dict):
        raise EngineeringLedgerError("entry counters are malformed")
    return entry.get("retryable") is False or any(
        counters.get(name, 0) >= MAX_ENGINEERING_ATTEMPTS for name in COUNTER_NAMES
    )


def record_engineering_outcome(
    ledger: Any,
    contract: dict[str, Any],
    reservation: dict[str, Any],
    bundle_or_artifact: dict[str, Any],
    code: str,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Record an outcome without mutating the input ledger.

    Returns ``(updated_ledger, entry, retryable)``. Identical replays are
    idempotent and never increment counters.
    """
    if not isinstance(code, str) or code not in ALLOWED_CODES:
        raise EngineeringLedgerError("outcome code is not allowlisted")
    try:
        normalized = validate_task_contract(contract)
    except (TaskContractError, ValueError) as exc:
        raise EngineeringLedgerError("engineering task contract is invalid") from exc

    if not isinstance(reservation, dict):
        raise EngineeringLedgerError("reservation must be an object")
    reservation_id = reservation.get("reservation_id")
    if not isinstance(reservation_id, str) or not 1 <= len(reservation_id) <= 80:
        raise EngineeringLedgerError("reservation id is invalid")
    if reservation.get("task_id") != normalized["task_id"]:
        raise EngineeringLedgerError("reservation does not match the task contract")
    if reservation.get("base_sha") != normalized["base_sha"]:
        raise EngineeringLedgerError("reservation base SHA does not match the contract")

    digest = _outcome_digest(bundle_or_artifact)
    safe = load_safe_ledger(ledger)
    key = namespaced_key(normalized["task_id"])
    existing = safe["entries"].get(key)

    if existing is not None:
        if (
            existing["reservation_id"] == reservation_id
            and existing["digest"] == digest
            and existing["code"] == code
        ):
            return copy.deepcopy(safe), copy.deepcopy(existing), existing["retryable"]
        if existing["reservation_id"] != reservation_id:
            raise EngineeringLedgerError("ledger entry belongs to a different reservation")

    counters = dict(existing["counters"]) if existing is not None else {name: 0 for name in COUNTER_NAMES}
    field = _CODE_COUNTER.get(code)
    if field is not None and code not in {AUDIT_SUCCESS, MANUAL_REVIEW_REQUIRED}:
        counters["attempts"] = min(counters["attempts"] + 1, MAX_ENGINEERING_ATTEMPTS)
        counters[field] = min(counters[field] + 1, MAX_ENGINEERING_ATTEMPTS)

    attempt_source = f"{reservation_id}:{digest}:{code}".encode("utf-8")
    entry = {
        "task_id": normalized["task_id"],
        "reservation_id": reservation_id,
        "digest": digest,
        "code": code,
        "counters": counters,
        "retryable": False,
        "attempt_id": hashlib.sha256(attempt_source).hexdigest(),
        "execution_enabled": False,
        "publication_enabled": False,
        "requires_owner_approval": True,
    }
    if code in {AUDIT_SUCCESS, MANUAL_REVIEW_REQUIRED}:
        entry["retryable"] = False
    else:
        # Decide from counters only; ``is_exhausted`` also inspects the final
        # retryable flag, which is not meaningful until after this assignment.
        entry["retryable"] = not any(
            counters[name] >= MAX_ENGINEERING_ATTEMPTS for name in COUNTER_NAMES
        )

    safe["entries"][key] = entry
    load_safe_ledger(safe)
    return copy.deepcopy(safe), copy.deepcopy(entry), entry["retryable"]
