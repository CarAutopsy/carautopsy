"""Read-only, privacy-bounded summary of the local Hive queue and outcome ledger.

This module never fetches Git, mutates state, dispatches tasks, or calls providers.
It summarizes only safe task identifiers and versioned outcome metadata; raw audit
prose, candidate payloads, source URLs, and provider responses are never rendered.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import sys
from typing import Any

try:
    from . import hive_outcomes
except ImportError:  # script execution from the repository root
    import hive_outcomes


MAX_INPUT_BYTES = 5_000_000
MAX_RECORDS = 20_000
MAX_ID_LENGTH = 128
MAX_LABEL_LENGTH = 100


class OwnerDigestError(ValueError):
    """Raised when a queue or outcome snapshot is malformed or oversized."""


def _parse_constant(value: str) -> None:
    raise OwnerDigestError(f"non-finite JSON number is not allowed: {value}")


def _parse_int(value: str) -> int:
    digits = value.lstrip("-")
    if len(digits) > 20:
        raise OwnerDigestError("JSON integer exceeds the 20-digit safety limit")
    try:
        return int(value)
    except ValueError as exc:
        raise OwnerDigestError("invalid JSON integer") from exc


def _read_array(path: Path) -> list[Any]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise OwnerDigestError(f"cannot read {path}: {exc}") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise OwnerDigestError(f"{path} exceeds the {MAX_INPUT_BYTES}-byte limit")
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_parse_constant, parse_int=_parse_int)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise OwnerDigestError(f"{path} is not valid UTF-8 JSON") from exc
    if not isinstance(value, list) or len(value) > MAX_RECORDS:
        raise OwnerDigestError(f"{path} must be an array of at most {MAX_RECORDS} records")
    return value


def _safe_text(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value.strip()


def _safe_task(task: Any) -> dict[str, str] | None:
    if not isinstance(task, dict):
        return None
    variant_id = _safe_text(task.get("variant_id"), MAX_ID_LENGTH)
    if variant_id is None:
        return None
    result = {"variant_id": variant_id}
    for field in ("make", "model"):
        value = _safe_text(task.get(field), MAX_LABEL_LENGTH)
        if value is not None:
            result[field] = value
    return result


def _safe_timestamp(value: Any) -> str | None:
    """Return only timezone-aware ISO-8601 timestamps."""
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return value


def _state_attempt_limits_exhausted(entry: dict[str, Any]) -> bool:
    """Mirror hive_state.exhausted_ids() top-level retry ceilings."""
    try:
        audit_limit = int(entry.get("max_attempts") or 3)
        research_limit = int(entry.get("max_research_attempts") or 3)
        attempts = int(entry.get("attempts") or 0)
        research_attempts = int(entry.get("research_attempts") or 0)
    except (TypeError, ValueError, OverflowError):
        raise OwnerDigestError("invalid top-level Hive attempt counters")
    if min(audit_limit, research_limit, attempts, research_attempts) < 0:
        raise OwnerDigestError("negative top-level Hive attempt counter")
    return attempts >= audit_limit or research_attempts >= research_limit


def _safe_failed_record(entry: Any) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(entry, dict):
        return None, "malformed"
    task = _safe_task(entry.get("task"))
    if task is None:
        return None, "malformed"

    effective = entry
    legacy_migrated = False
    manual = hive_outcomes.requires_manual_review(entry)
    if manual:
        migrated, recognized = hive_outcomes.migrate_legacy_entry(entry)
        if recognized:
            effective = migrated
            manual = False
            legacy_migrated = True

    outcome = effective.get("outcome") if isinstance(effective.get("outcome"), dict) else {}
    code = outcome.get("code") if not manual else hive_outcomes.MANUAL_REVIEW_REQUIRED
    if not isinstance(code, str) or code not in hive_outcomes.OUTCOME_CODES:
        code = hive_outcomes.MANUAL_REVIEW_REQUIRED
        manual = True

    state_exhausted = False
    if not manual:
        try:
            state_exhausted = _state_attempt_limits_exhausted(effective)
        except OwnerDigestError:
            manual = True
            code = hive_outcomes.MANUAL_REVIEW_REQUIRED
            outcome = {}

    safe_counters = {}
    if not manual:
        counters = outcome["counters"]
        safe_counters = {
            field: counters[field]
            for field in (
                "provider_attempts", "format_attempts", "provenance_attempts",
                "attempts", "research_attempts",
            )
        }

    retryable = not manual and not state_exhausted and outcome.get("retryable") is True
    exhausted = manual or state_exhausted or hive_outcomes.exhausted_outcome(effective)
    safe = {
        "task": task,
        "outcome_code": code,
        "stage": _safe_text(outcome.get("stage"), 40) if not manual else "manual_review",
        "at": _safe_timestamp(outcome.get("at")) if not manual else None,
        "retryable": retryable,
        "exhausted": exhausted,
        "manual_review_required": manual,
        "counters": safe_counters,
    }
    if legacy_migrated:
        safe["legacy_migrated"] = True
    categories = effective.get("defect_categories")
    if not manual and isinstance(categories, list):
        allowed = set(hive_outcomes.DEFECT_CATEGORY_MARKERS) | {"unspecified_quality_defect"}
        safe["defect_categories"] = sorted({
            item for item in categories if isinstance(item, str) and item in allowed
        })
    return safe, code

def build_digest(
    queue: list[Any],
    failed: list[Any],
    *,
    snapshot_source: str = "working-tree",
    state_integrity: str = "not-verified",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic safe summary from already-loaded local snapshots."""
    if not isinstance(queue, list) or not isinstance(failed, list):
        raise OwnerDigestError("queue and failed ledger must both be arrays")
    if len(queue) > MAX_RECORDS or len(failed) > MAX_RECORDS:
        raise OwnerDigestError("queue or failed ledger exceeds the record limit")

    source = _safe_text(snapshot_source, 64)
    integrity = _safe_text(state_integrity, 64)
    if source is None or integrity is None:
        raise OwnerDigestError("snapshot source and state integrity labels must be bounded text")

    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    if not isinstance(timestamp, str) or len(timestamp) > 64:
        raise OwnerDigestError("generated_at must be a bounded ISO-8601 string")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OwnerDigestError("generated_at must be ISO-8601") from exc
    if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
        raise OwnerDigestError("generated_at must include a timezone")

    safe_queue = []
    malformed_queue = 0
    seen_queue = set()
    duplicate_queue = 0
    for item in queue:
        safe = _safe_task(item)
        if safe is None:
            malformed_queue += 1
            continue
        if safe["variant_id"] in seen_queue:
            duplicate_queue += 1
        seen_queue.add(safe["variant_id"])
        safe_queue.append(safe)

    safe_failed = []
    malformed_failed = 0
    counts: Counter[str] = Counter()
    for item in failed:
        safe, code = _safe_failed_record(item)
        if safe is None:
            malformed_failed += 1
            counts[hive_outcomes.MANUAL_REVIEW_REQUIRED] += 1
            continue
        safe_failed.append(safe)
        counts[code] += 1

    manual_count = sum(item["manual_review_required"] for item in safe_failed) + malformed_failed
    exhausted_count = sum(item["exhausted"] for item in safe_failed) + malformed_failed
    retryable_count = sum(item["retryable"] for item in safe_failed)
    return {
        "schema_version": 1,
        "generated_at": timestamp,
        "snapshot": {
            "source": source,
            "state_integrity": integrity,
            "authority_note": (
                "This is a read-only snapshot of the supplied checkout files; "
                "it does not fetch or reconcile origin/hive/state."
            ),
        },
        "summary": {
            "queued": len(safe_queue),
            "failed_records": len(safe_failed) + malformed_failed,
            "retryable": retryable_count,
            "exhausted": exhausted_count,
            "manual_review_required": manual_count,
            "malformed_queue_records": malformed_queue,
            "duplicate_queue_ids": duplicate_queue,
            "malformed_failed_records": malformed_failed,
            "outcomes_by_code": dict(sorted(counts.items())),
        },
        "queue": safe_queue,
        "failed": safe_failed,
    }


def _markdown_text(value: Any) -> str:
    """Escape untrusted snapshot labels before placing them in Markdown."""
    return html.escape(str(value), quote=True).replace("`", "&#96;")


def render_markdown(report: dict[str, Any]) -> str:
    """Render a concise owner-facing digest without untrusted raw text."""
    summary = report["summary"]
    snapshot = report["snapshot"]
    lines = [
        "# Hive Owner Digest",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Snapshot: `{_markdown_text(snapshot['source'])}`",
        f"- State integrity: `{_markdown_text(snapshot['state_integrity'])}`",
        "- Mode: **read-only; no fetch, reconciliation, dispatch, or provider calls**",
        "",
        "## Summary",
        "",
        f"- Queued: **{summary['queued']}**",
        f"- Failed ledger records: **{summary['failed_records']}**",
        f"- Retryable: **{summary['retryable']}**",
        f"- Exhausted: **{summary['exhausted']}**",
        f"- Manual review required: **{summary['manual_review_required']}**",
        f"- Malformed queue / failed records: **{summary['malformed_queue_records']} / {summary['malformed_failed_records']}**",
        f"- Duplicate queue IDs: **{summary['duplicate_queue_ids']}**",
        "",
        "## Failed outcome classes",
        "",
    ]
    if summary["outcomes_by_code"]:
        for code, count in summary["outcomes_by_code"].items():
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("- None")
    lines.extend(["", "## Queued tasks", ""])
    if report["queue"]:
        for task in report["queue"]:
            label = " — ".join(_markdown_text(task.get(field, "")) for field in ("make", "model") if task.get(field))
            suffix = f" ({label})" if label else ""
            lines.append(f"- `{_markdown_text(task['variant_id'])}`{suffix}")
    else:
        lines.append("- None")
    lines.extend(["", "## Failed tasks", ""])
    if report["failed"]:
        for item in report["failed"]:
            task = item["task"]
            lines.append(
                f"- `{_markdown_text(task['variant_id'])}`: `{item['outcome_code']}`; "
                f"retryable={str(item['retryable']).lower()}; "
                f"exhausted={str(item['exhausted']).lower()}; "
                f"manual_review={str(item['manual_review_required']).lower()}"
            )
    else:
        lines.append("- None")
    lines.extend(["", f"> {_markdown_text(snapshot['authority_note'])}", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository checkout root")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--snapshot-source", default="working-tree")
    parser.add_argument("--state-integrity", default="not-verified")
    args = parser.parse_args(argv)
    try:
        tasks = args.root / "tasks"
        report = build_digest(
            _read_array(tasks / "queue.json"),
            _read_array(tasks / "failed.json"),
            snapshot_source=args.snapshot_source,
            state_integrity=args.state_integrity,
        )
    except (OwnerDigestError, OSError) as exc:
        print(f"Hive owner digest failed: {exc}", file=sys.stderr)
        return 2
    output = render_markdown(report) if args.format == "markdown" else json.dumps(
        report, indent=2, ensure_ascii=False, allow_nan=False
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
