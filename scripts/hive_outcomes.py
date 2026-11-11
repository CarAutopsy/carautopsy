"""Versioned, allowlisted Hive retry outcomes and bounded counter accounting."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

OUTCOME_SCHEMA_VERSION = 1
PROVIDER_TRANSPORT_FAILURE = "provider_transport_failure"
RESPONSE_FORMAT_FAILURE = "response_format_failure"
PROVENANCE_REJECTION = "provenance_rejection"
VEHICLE_QUALITY_REJECTION = "vehicle_quality_rejection"
AUDIT_SUCCESS = "audit_success"
MANUAL_REVIEW_REQUIRED = "manual_review_required"
OUTCOME_CODES = frozenset({
    PROVIDER_TRANSPORT_FAILURE, RESPONSE_FORMAT_FAILURE, PROVENANCE_REJECTION,
    VEHICLE_QUALITY_REJECTION, AUDIT_SUCCESS, MANUAL_REVIEW_REQUIRED,
})
COUNTER_BY_OUTCOME = {
    PROVIDER_TRANSPORT_FAILURE: ("provider_attempts", 3),
    RESPONSE_FORMAT_FAILURE: ("format_attempts", 3),
    PROVENANCE_REJECTION: ("provenance_attempts", 2),
    VEHICLE_QUALITY_REJECTION: ("attempts", 3),
}
PROVENANCE_MARKERS = ("provenance", "source url", "source-url", "citation", "coc", "certificate of conformity", "retrieval", "official url")


def classify_research_response(raw, parsed):
    """Classify a researcher result without retaining its response body."""
    if not isinstance(raw, str) or not raw.strip():
        return PROVIDER_TRANSPORT_FAILURE
    if not isinstance(parsed, dict) or not isinstance(parsed.get("identity"), dict):
        return RESPONSE_FORMAT_FAILURE
    return None


def classify_audit_results(audits):
    """Classify the independent audit quorum using explicit status strings only."""
    if not isinstance(audits, list) or len(audits) < 2:
        return PROVIDER_TRANSPORT_FAILURE
    verdicts = [str(item.get("verdict", "")).strip() for item in audits if isinstance(item, dict)]
    if len(verdicts) != len(audits):
        return RESPONSE_FORMAT_FAILURE
    if any(value.upper() == "OFFLINE" for value in verdicts):
        return PROVIDER_TRANSPORT_FAILURE
    if any(value.upper() == "INVALID_AUDIT_RESPONSE" or not value for value in verdicts):
        return RESPONSE_FORMAT_FAILURE
    failures = [value for value in verdicts if value.upper().startswith("FAIL:")]
    if failures:
        if any(any(marker in value.lower() for marker in PROVENANCE_MARKERS) for value in failures):
            return PROVENANCE_REJECTION
        return VEHICLE_QUALITY_REJECTION
    if all(value.upper() == "PASS" for value in verdicts):
        return AUDIT_SUCCESS
    return RESPONSE_FORMAT_FAILURE


def _prior_counters(previous):
    """Return trusted counters only from a recognized versioned outcome record."""
    if previous is None:
        return {"provider_attempts": 0, "format_attempts": 0, "provenance_attempts": 0, "attempts": 0, "research_attempts": 0}
    outcome = previous.get("outcome")
    if not isinstance(outcome, dict) or type(outcome.get("schema_version")) is not int or outcome.get("schema_version") != OUTCOME_SCHEMA_VERSION:
        return None
    code = outcome.get("code")
    if code not in OUTCOME_CODES or code == AUDIT_SUCCESS:
        return None
    if not isinstance(outcome.get("attempt_id"), str) or not outcome["attempt_id"] or len(outcome["attempt_id"]) > 80:
        return None
    if not isinstance(outcome.get("stage"), str) or not outcome["stage"] or len(outcome["stage"]) > 40:
        return None
    if type(outcome.get("retryable")) is not bool or not isinstance(outcome.get("at"), str) or not outcome["at"]:
        return None
    if not isinstance(outcome.get("provider_statuses"), list):
        return None
    counters = outcome.get("counters")
    if not isinstance(counters, dict):
        return None
    names = ("provider_attempts", "format_attempts", "provenance_attempts", "attempts", "research_attempts")
    result = {}
    for name in names:
        value = counters.get(name, 0)
        if type(value) is not int or value < 0:
            return None
        result[name] = value
    ceilings = {"provider_attempts": 3, "format_attempts": 3, "provenance_attempts": 2, "attempts": 3, "research_attempts": 3}
    if any(result[name] > limit for name, limit in ceilings.items()):
        return None
    code = outcome["code"]
    if code in COUNTER_BY_OUTCOME:
        field, ceiling = COUNTER_BY_OUTCOME[code]
        expected_retryable = result[field] < ceiling and all(
            result[name] < limit for name, limit in {
                "provider_attempts": 3, "format_attempts": 3,
                "provenance_attempts": 2, "attempts": 3,
            }.items()
        )
        if outcome["retryable"] != expected_retryable:
            return None
    elif outcome["retryable"]:
        return None
    return result


def record_outcome(task, previous, code, *, stage, provider_statuses=None, now=None, attempt_id=None):
    """Build a safe durable entry and indicate whether its class may be retried."""
    if code not in OUTCOME_CODES or code == AUDIT_SUCCESS:
        raise ValueError("failure recorder requires an allowlisted non-success outcome")
    counters = _prior_counters(previous)
    if counters is None:
        code = MANUAL_REVIEW_REQUIRED
        counters = {"provider_attempts": 0, "format_attempts": 0, "provenance_attempts": 0, "attempts": 0, "research_attempts": 0}
        stage = "legacy_reconciliation"
    retryable = False
    if code in COUNTER_BY_OUTCOME:
        field, ceiling = COUNTER_BY_OUTCOME[code]
        counters[field] += 1
        retryable = counters[field] < ceiling and all(
            counters[name] < limit for name, limit in {
                "provider_attempts": 3, "format_attempts": 3,
                "provenance_attempts": 2, "attempts": 3,
            }.items()
        )
    safe_statuses = []
    for item in provider_statuses or []:
        if isinstance(item, dict):
            provider = item.get("provider")
            status = item.get("status")
            if isinstance(provider, str) and len(provider) <= 40 and isinstance(status, str) and status in {"PASS", "OFFLINE", "INVALID", "FAIL"}:
                safe_statuses.append({"provider": provider, "status": status})
    timestamp = now or datetime.now(timezone.utc).isoformat()
    entry = {"task": task}
    if isinstance(previous, dict):
        for key in ("audits", "candidate", "verdict", "at"):
            if key in previous:
                entry[key] = previous[key]
    entry["verdict"] = code.upper()
    entry["at"] = timestamp
    entry["outcome"] = {
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "code": code,
        "attempt_id": attempt_id or str(uuid.uuid4()),
        "stage": str(stage)[:40],
        "retryable": retryable,
        "at": timestamp,
        "provider_statuses": safe_statuses,
        "counters": counters,
    }
    return entry, retryable



def migrate_legacy_entry(entry):
    """Migrate only a fully classifiable one-attempt audit record; otherwise leave it untouched."""
    if not isinstance(entry, dict) or not isinstance(entry.get("task"), dict):
        return entry, False
    if isinstance(entry.get("outcome"), dict):
        return entry, False
    if entry.get("verdict") != "INDEPENDENT_AUDIT_FAILED" or entry.get("attempts") != 1:
        return entry, False
    audits = entry.get("audits")
    if not isinstance(audits, list) or len(audits) < 2:
        return entry, False
    recognized_verdicts = []
    for item in audits:
        if not isinstance(item, dict) or not isinstance(item.get("verdict"), str):
            return entry, False
        verdict = item["verdict"].strip()
        if verdict.upper() not in {"PASS", "OFFLINE", "INVALID_AUDIT_RESPONSE"} and not verdict.upper().startswith("FAIL:"):
            return entry, False
        recognized_verdicts.append(verdict)
    code = classify_audit_results(audits)
    if code not in COUNTER_BY_OUTCOME:
        return entry, False
    safe_audits = []
    for item in audits:
        verdict = str(item.get("verdict", "")).strip()
        status = "PASS" if verdict.upper() == "PASS" else (
            "OFFLINE" if verdict.upper() == "OFFLINE" else (
                "INVALID" if verdict.upper() == "INVALID_AUDIT_RESPONSE" else "FAIL"
            )
        )
        safe_audits.append({
            "provider": str(item.get("provider", "auditor"))[:40],
            "vendor": str(item.get("vendor", "unknown"))[:40],
            "verdict": status,
        })
    migrated, _ = record_outcome(
        entry["task"], None, code, stage="legacy_migration",
        provider_statuses=safe_audits, now=entry.get("at"),
    )
    migrated["audits"] = safe_audits
    candidate = entry.get("candidate")
    if isinstance(candidate, dict):
        candidate = dict(candidate)
        extensions = candidate.get("extensions")
        if isinstance(extensions, dict) and isinstance(extensions.get("hive"), dict):
            extensions = dict(extensions)
            hive = dict(extensions["hive"])
            hive["audits"] = safe_audits
            extensions["hive"] = hive
            candidate["extensions"] = extensions
        migrated["candidate"] = candidate
    counters = migrated["outcome"]["counters"]
    migrated.update({
        "attempts": counters["attempts"], "max_attempts": 3,
        "research_attempts": counters["research_attempts"], "max_research_attempts": 3,
        "provider_attempts": counters["provider_attempts"],
        "format_attempts": counters["format_attempts"],
        "provenance_attempts": counters["provenance_attempts"],
    })
    return migrated, True

def requires_manual_review(entry):
    """Legacy, malformed, or unknown outcome records are quarantined."""
    if not isinstance(entry, dict):
        return True
    outcome = entry.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("schema_version") != OUTCOME_SCHEMA_VERSION:
        return True
    if outcome.get("code") not in OUTCOME_CODES:
        return True
    return _prior_counters(entry) is None or outcome.get("code") == MANUAL_REVIEW_REQUIRED


def exhausted_outcome(entry):
    """Whether a versioned outcome has exhausted its own retry ceiling."""
    if requires_manual_review(entry):
        return True
    outcome = entry["outcome"]
    return any(
        outcome["counters"][field] >= ceiling
        for field, ceiling in {
            "provider_attempts": 3, "format_attempts": 3,
            "provenance_attempts": 2, "attempts": 3,
        }.items()
    )
