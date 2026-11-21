"""Offline vehicle catalog quality, completeness and refresh-planning tool.

Reuses ``scripts.validate_catalog.validate_catalog`` for structural validation
and adds canonical identity normalization, duplicate/conflict detection,
provenance confidence scoring, missing-data metrics, staleness detection and a
deterministic owner-reviewed refresh plan. No network, provider call, secret
access or catalog mutation is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_catalog import validate_catalog

DEFAULT_CATALOG = ROOT / "catalog" / "variants"
DEFAULT_SCHEMA = ROOT / "schemas" / "vehicle-variant.schema.json"
DEFAULT_REPORT = ROOT / "reports" / "catalog-quality.json"
MAX_INPUT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_SOURCE_AGE_DAYS = 365
TIER_SCORE = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "official": 4}
GATES = {"HIVE_RESEARCH_PAUSED": True, "VERIFIED_RETRIEVAL_AVAILABLE": False}

OFFER_FIELDS = ("country", "currency", "list_price_minor", "price_as_of", "availability")

FIELD_SPECS: tuple[tuple[str, str, bool, frozenset[str] | None], ...] = (
    ("identity.make", "identity", True, None),
    ("identity.model", "identity", True, None),
    ("identity.model_slug", "identity", False, None),
    ("identity.generation", "identity", False, None),
    ("identity.variant_name", "identity", False, None),
    ("identity.body_style", "identity", False, None),
    ("identity.powertrain", "identity", True, None),
    ("identity.model_year_from", "identity", True, None),
    ("performance.power_w", "performance", True, None),
    ("performance.accel_0_100_s", "performance", False, None),
    ("performance.drive", "performance", False, None),
    ("performance.combustion_engine_power_w", "performance", True, frozenset({"ice", "hev", "phev"})),
    ("energy.battery_usable_wh", "energy", True, frozenset({"bev", "phev"})),
    ("energy.dc_peak_w", "energy", False, frozenset({"bev", "phev"})),
    ("energy.consumption_wh_km.wltp_combined", "energy", False, frozenset({"bev", "phev"})),
    ("energy.range_m.wltp", "energy", False, frozenset({"bev", "phev"})),
    ("emissions.co2_wltp_gpkm", "emissions", True, frozenset({"ice", "hev", "phev"})),
    ("dimensions.length_mm", "dimensions", False, None),
    ("dimensions.width_mm", "dimensions", False, None),
    ("dimensions.height_mm", "dimensions", False, None),
    ("dimensions.wheelbase_mm", "dimensions", False, None),
    ("dimensions.curb_mass_kg", "dimensions", True, None),
    ("warranty.vehicle_years", "warranty", False, None),
    ("warranty.battery_years", "warranty", False, frozenset({"bev", "phev"})),
    *((f"offers.{field}", "offers", True, None) for field in OFFER_FIELDS),
    ("provenance.sources", "provenance", True, None),
)

class QualityError(ValueError):
    """Raised when quality evidence cannot be built."""


def slugify(value: Any) -> str | None:
    """Return a stable lowercase slug or None for absent values."""
    if not isinstance(value, str) or not value.strip():
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")
    return slug or None


def nested(record: dict[str, Any], path: str) -> Any:
    """Read a dot-separated path without mutating the record."""
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def present(value: Any) -> bool:
    """Return True for a populated value; null means unknown by protocol."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def parse_day(value: Any, field: str) -> date:
    """Parse a date-only or timezone-aware timestamp into a UTC date."""
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str) or not value.strip():
        raise QualityError(f"{field} must be a non-empty date")
    text = value.strip()
    if len(text) == 10:
        return date.fromisoformat(text)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QualityError(f"{field} must include a timezone")
    return parsed.astimezone(UTC).date()


def normalize_identity(record: dict[str, Any], variant_id: str) -> dict[str, Any]:
    """Normalize make/model/generation identity without mutating the record."""
    identity = record.get("identity")
    if not isinstance(identity, dict):
        identity = {}
    make_slug = slugify(identity.get("make")) or slugify(variant_id.split(".")[0] if "." in variant_id else None)
    model_slug = slugify(identity.get("model")) or slugify(identity.get("model_slug"))
    generation_slug = slugify(identity.get("generation")) or slugify(identity.get("generation_slug"))
    # The stable variant slug is the identity component; the display name may
    # be shared by different variants and must not collapse their keys.
    variant_slug = slugify(identity.get("variant_slug")) or slugify(identity.get("variant_name"))
    year = identity.get("model_year_from")
    if isinstance(year, bool) or not isinstance(year, int):
        year = None
    powertrain = identity.get("powertrain")
    powertrain = powertrain.strip().casefold() if isinstance(powertrain, str) and powertrain.strip() else None
    key = "|".join(part or "-" for part in (make_slug, model_slug, generation_slug, variant_slug, str(year or "-")))
    return {
        "make_slug": make_slug,
        "model_slug": model_slug,
        "generation_slug": generation_slug,
        "variant_slug": variant_slug,
        "model_year_from": year,
        "powertrain": powertrain,
        "canonical_key": key,
    }


def confidence_tier(record: dict[str, Any]) -> dict[str, Any]:
    """Score provenance from evidence-bearing source entries."""
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return {"tier": "unknown", "score": 0, "independent_sources": 0, "reviewed": False}
    sources = provenance.get("sources")
    sources = sources if isinstance(sources, list) else []
    # Each tier must stay attached to the evidence reference that supports it;
    # a URL from one entry cannot promote an unrelated entry's confidence.
    tiers: list[str] = []
    urls: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        raw = source.get("confidence") or source.get("tier") or "low"
        tier = str(raw).strip().casefold()
        if tier not in TIER_SCORE:
            tier = "low"
        tiers.append(tier)
        urls.add(url.strip())
    independent = len(urls)
    if not tiers:
        return {
            "tier": "unknown",
            "score": 0,
            "independent_sources": 0,
            "reviewed": isinstance(provenance.get("reviewed_by"), str) and bool(provenance["reviewed_by"].strip()),
        }
    highest = max(tiers, key=lambda item: TIER_SCORE[item])
    if highest == "official" and independent >= 1:
        tier = "official"
    elif independent >= 2 and TIER_SCORE[highest] >= TIER_SCORE["medium"]:
        tier = "high"
    elif independent >= 1 and TIER_SCORE[highest] >= TIER_SCORE["medium"]:
        tier = "medium"
    else:
        tier = "low"
    reviewed = isinstance(provenance.get("reviewed_by"), str) and bool(provenance["reviewed_by"].strip())
    return {
        "tier": tier,
        "score": TIER_SCORE[tier],
        "independent_sources": independent,
        "reviewed": reviewed,
    }


def coverage(record: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    """Compute field-level completeness for one variant."""
    powertrain = identity["powertrain"] or ""
    sections: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    critical_missing: list[str] = []
    required_total = populated_total = 0
    for path, section, critical, modes in FIELD_SPECS:
        if modes is not None and powertrain not in modes:
            continue
        info = sections.setdefault(section, {"required": 0, "populated": 0, "missing": []})
        required_total += 1
        info["required"] += 1
        if path.startswith("offers."):
            field = path.split(".", 1)[1]
            value = any(
                present(offer.get(field))
                for offer in (record.get("offers") or [])
                if isinstance(offer, dict)
            ) if isinstance(record.get("offers"), list) else False
        else:
            value = nested(record, path)
        if present(value):
            populated_total += 1
            info["populated"] += 1
        else:
            info["missing"].append(path)
            missing.append(path)
            if critical:
                critical_missing.append(path)
    offer_rows = record.get("offers")
    offer_rows = offer_rows if isinstance(offer_rows, list) else []
    complete_offers = [
        offer for offer in offer_rows
        if isinstance(offer, dict) and all(present(offer.get(field)) for field in OFFER_FIELDS)
    ]
    for section in sections.values():
        total = section["required"]
        section["ratio"] = round(section["populated"] / total, 4) if total else 1.0
    ratio = round(populated_total / required_total, 4) if required_total else 1.0
    return {
        "required_fields": required_total,
        "populated_fields": populated_total,
        "missing_fields": missing,
        "critical_missing_fields": critical_missing,
        "completeness_ratio": ratio,
        "complete": ratio == 1.0,
        "offers_total": len(offer_rows),
        "offers_complete": len(complete_offers),
        "sections": sections,
    }


def source_freshness(
    record: dict[str, Any],
    now: datetime,
    max_age_days: int,
    variant_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return per-source freshness and findings for stale or invalid sources."""
    provenance = record.get("provenance")
    sources = provenance.get("sources") if isinstance(provenance, dict) else []
    sources = sources if isinstance(sources, list) else []
    details: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        item = source if isinstance(source, dict) else {}
        name = str(item.get("name") or item.get("url") or f"source-{index}")
        if not present(item.get("retrieved")):
            details.append({"name": name, "status": "UNVERIFIED", "age_days": None})
            findings.append(_finding("UNVERIFIED_PROVENANCE", variant_id, f"missing retrieved date: {name}", "WARNING"))
            continue
        try:
            retrieved = parse_day(item.get("retrieved"), "retrieved")
        except (QualityError, ValueError):
            details.append({"name": name, "status": "INVALID_TIMESTAMP", "age_days": None})
            findings.append(_finding("INVALID_PROVENANCE_TIMESTAMP", variant_id, f"invalid retrieved date: {name}", "ERROR"))
            continue
        age = (now.date() - retrieved).days
        if age < 0:
            status = "INVALID_TIMESTAMP"
            findings.append(_finding("FUTURE_PROVENANCE", variant_id, f"future retrieved date: {name}", "ERROR"))
        elif age > max_age_days:
            status = "STALE"
            findings.append(_finding("STALE_SOURCE", variant_id, f"{name} is {age} days old", "WARNING"))
        else:
            status = "CURRENT"
        details.append({"name": name, "status": status, "age_days": age})
    return details, findings


def _finding(category: str, record_id: str, message: str, severity: str) -> dict[str, str]:
    return {"category": category, "severity": severity, "record_id": record_id, "message": message}


def load_catalog(catalog_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Load bounded catalog records sorted by path."""
    catalog_dir = catalog_dir.resolve()
    if not catalog_dir.is_dir():
        raise QualityError(f"catalog directory does not exist: {catalog_dir}")
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(catalog_dir.glob("*.json")):
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise QualityError(f"{path}: record exceeds {MAX_INPUT_BYTES} bytes")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualityError(f"{path}: invalid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise QualityError(f"{path}: record must be a JSON object")
        records.append((path, record))
    return records


def catalog_sha256(records: list[tuple[Path, dict[str, Any]]]) -> str:
    """Hash path/record pairs deterministically."""
    payload = [
        {"path": path.name, "record": record}
        for path, record in sorted(records, key=lambda item: item[0].name)
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def has_sufficient_identity(identity: dict[str, Any]) -> bool:
    """Whether an identity is specific enough to support a duplicate verdict."""
    return bool(
        identity.get("make_slug")
        and identity.get("model_slug")
        and isinstance(identity.get("model_year_from"), int)
        and (identity.get("generation_slug") or identity.get("variant_slug"))
        and identity.get("canonical_key")
    )


def detect_duplicates(
    records: list[tuple[Path, dict[str, Any]]],
    identities: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    """Detect duplicate variant IDs, identities and conflicting specifications."""
    findings: list[dict[str, str]] = []
    by_variant_id: dict[str, list[str]] = {}
    by_identity: dict[str, list[str]] = {}
    for path, record in records:
        variant_id = str(record.get("variant_id") or path.stem)
        by_variant_id.setdefault(variant_id, []).append(variant_id)
        identity = identities[variant_id]
        if has_sufficient_identity(identity):
            by_identity.setdefault(identity["canonical_key"], []).append(variant_id)
    for variant_id, items in sorted(by_variant_id.items()):
        if len(items) > 1:
            findings.append(_finding("DUPLICATE_VARIANT_ID", variant_id, f"used by {len(items)} records", "ERROR"))
    for key, items in sorted(by_identity.items()):
        unique = sorted(set(items))
        if len(unique) > 1:
            findings.append(_finding("DUPLICATE_IDENTITY", unique[0], f"identity key shared by {', '.join(unique)}", "ERROR"))
            first = next(record for path, record in records if str(record.get("variant_id") or path.stem) == unique[0])
            for other_id in unique[1:]:
                other = next(record for path, record in records if str(record.get("variant_id") or path.stem) == other_id)
                watched = (
                    "performance.power_w", "energy.battery_usable_wh", "identity.body_style",
                    "dimensions.curb_mass_kg", "offers",
                )
                for field in watched:
                    left, right = nested(first, field), nested(other, field)
                    if present(left) and present(right) and json.dumps(left, sort_keys=True) != json.dumps(right, sort_keys=True):
                        findings.append(_finding(
                            "CONFLICTING_SPECIFICATION", other_id,
                            f"{field} differs from {unique[0]}", "ERROR",
                        ))
    return findings


def refresh_plan(
    coverages: dict[str, dict[str, Any]],
    confidences: dict[str, dict[str, Any]],
    freshness: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Build a deterministic, non-executing refresh plan."""
    plan: list[dict[str, Any]] = []
    for variant_id in sorted(coverages):
        cov = coverages[variant_id]
        conf = confidences[variant_id]
        stale = [item["name"] for item in freshness[variant_id] if item["status"] != "CURRENT"]
        reasons: list[str] = []
        priority = "P2"
        if cov["critical_missing_fields"] or conf["tier"] == "low" or stale:
            priority = "P1"
            if cov["critical_missing_fields"]:
                reasons.append("critical fields missing: " + ", ".join(cov["critical_missing_fields"]))
            if conf["tier"] == "low":
                reasons.append("low provenance confidence")
            if stale:
                reasons.append("stale or unverified sources: " + ", ".join(stale))
        elif not cov["complete"]:
            reasons.append("non-critical fields missing: " + ", ".join(cov["missing_fields"]))
        plan.append({
            "variant_id": variant_id,
            "priority": priority,
            "reasons": reasons,
            "refresh_enabled": False,
            "network_permitted": False,
            "action": "owner-reviewed research only; no execution by this tool",
        })
    order = {"P0": 0, "P1": 1, "P2": 2}
    plan.sort(key=lambda item: (order[item["priority"]], item["variant_id"]))
    return plan


def preflight_input_sizes(catalog_dir: Path) -> None:
    """Reject oversized catalog files before any structural validation loads them."""
    catalog_dir = catalog_dir.resolve()
    if not catalog_dir.is_dir():
        return
    for path in sorted(catalog_dir.glob("*.json")):
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise QualityError(f"{path}: record exceeds {MAX_INPUT_BYTES} bytes")


def assert_safe_report_path(report_path: Path, catalog_dir: Path) -> Path:
    """Resolve a report path and reject any alias that points into the catalog."""
    resolved_report = report_path.resolve()
    resolved_catalog = catalog_dir.resolve()
    if resolved_report == resolved_catalog or resolved_report.is_relative_to(resolved_catalog):
        raise QualityError("report path must not overlap the catalog directory")
    if resolved_catalog.is_dir():
        for record_path in sorted(resolved_catalog.glob("*.json")):
            if resolved_report == record_path.resolve():
                raise QualityError("report path must not overwrite a catalog record")
    return resolved_report


def build_report(
    catalog_dir: Path = DEFAULT_CATALOG,
    schema_path: Path = DEFAULT_SCHEMA,
    now: datetime | None = None,
    max_source_age_days: int = DEFAULT_MAX_SOURCE_AGE_DAYS,
) -> dict[str, Any]:
    """Build a deterministic machine-readable catalog quality report."""
    evaluation_time = now or datetime.now(UTC)
    if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
        raise QualityError("now must include a timezone")
    evaluation_time = evaluation_time.astimezone(UTC)
    preflight_input_sizes(catalog_dir)
    structural_errors = validate_catalog(catalog_dir, schema_path)
    findings = [
        _finding("STRUCTURAL_ERROR", "<catalog>", message, "ERROR")
        for message in structural_errors
    ]
    records = load_catalog(catalog_dir) if catalog_dir.is_dir() else []
    identities: dict[str, dict[str, Any]] = {}
    coverages: dict[str, dict[str, Any]] = {}
    coverage_records: list[dict[str, Any]] = []
    confidences: dict[str, dict[str, Any]] = {}
    freshness: dict[str, list[dict[str, Any]]] = {}
    for path, record in records:
        variant_id = str(record.get("variant_id") or path.stem)
        identity = normalize_identity(record, variant_id)
        identities[variant_id] = identity
        record_coverage = coverage(record, identity)
        coverage_records.append(record_coverage)
        coverages[variant_id] = record_coverage
        confidences[variant_id] = confidence_tier(record)
        details, freshness_findings = source_freshness(record, evaluation_time, max_source_age_days, variant_id)
        freshness[variant_id] = details
        findings.extend(freshness_findings)
        for field in coverages[variant_id]["critical_missing_fields"]:
            findings.append(_finding("MISSING_CRITICAL_FIELD", variant_id, field, "WARNING"))
    findings.extend(detect_duplicates(records, identities))
    findings.sort(key=lambda item: (item["severity"], item["category"], item["record_id"], item["message"]))
    # Aggregate per record so duplicate variant IDs still contribute every
    # record's measurements to the catalog-level totals.
    required = sum(item["required_fields"] for item in coverage_records)
    populated = sum(item["populated_fields"] for item in coverage_records)
    sections: dict[str, dict[str, int]] = {}
    for cov in coverage_records:
        for name, info in cov["sections"].items():
            summary = sections.setdefault(name, {"required": 0, "populated": 0})
            summary["required"] += int(info["required"])
            summary["populated"] += int(info["populated"])
    for item in sections.values():
        item["ratio"] = round(item["populated"] / item["required"], 4) if item["required"] else 1.0
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "generated_at": evaluation_time.isoformat().replace("+00:00", "Z"),
        "catalog_sha256": catalog_sha256(records),
        "gates": dict(GATES),
        "refresh_execution_enabled": False,
        "network_calls": 0,
        "provider_calls": 0,
        "variant_count": len(records),
        "structural_error_count": len(structural_errors),
        "blocking_finding_count": sum(1 for item in findings if item["severity"] == "ERROR"),
        "completeness": {
            "required_fields": required,
            "populated_fields": populated,
            "ratio": round(populated / required, 4) if required else 1.0,
            "complete_variants": sum(1 for item in coverage_records if item["complete"]),
            "measured_records": len(coverage_records),
            "sections": sections,
        },
        "confidence_counts": {
            tier: sum(1 for item in confidences.values() if item["tier"] == tier)
            for tier in sorted(TIER_SCORE)
        },
        "variants": {
            variant_id: {
                "identity": identities[variant_id],
                "confidence": confidences[variant_id],
                "coverage": coverages[variant_id],
                "source_freshness": freshness[variant_id],
            }
            for variant_id in sorted(identities)
        },
        "findings": findings,
        "refresh_plan": refresh_plan(coverages, confidences, freshness),
    }
    report["report_sha256"] = report_digest(report)
    return report


def report_digest(report: dict[str, Any]) -> str:
    """Hash a report without environment-specific generated_at/report_sha256."""
    canonical = dict(report)
    canonical.pop("generated_at", None)
    canonical.pop("report_sha256", None)
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def write_report(report: dict[str, Any], path: Path) -> None:
    """Write the machine-readable report atomically enough for CI artifacts."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.stat().st_size if path.exists() else False:
        path.unlink()
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--now", default=None, help="timezone-aware ISO-8601 evaluation timestamp")
    parser.add_argument("--max-source-age-days", type=int, default=DEFAULT_MAX_SOURCE_AGE_DAYS)
    parser.add_argument("--fail-on", choices=("none", "structural", "blocking"), default="blocking")
    args = parser.parse_args(argv)
    try:
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise QualityError("--now must include a timezone")
        if args.max_source_age_days < 1:
            raise QualityError("--max-source-age-days must be positive")
        assert_safe_report_path(args.report, args.catalog_dir)
        report = build_report(args.catalog_dir, args.schema, now, args.max_source_age_days)
        write_report(report, args.report)
    except (QualityError, ValueError) as exc:
        print(f"catalog-quality: {exc}", file=sys.stderr)
        return 2
    print(
        f"variants={report['variant_count']} completeness={report['completeness']['ratio']:.4f} "
        f"blocking={report['blocking_finding_count']} report={args.report}"
    )
    if args.fail_on == "structural" and report["structural_error_count"]:
        return 1
    if args.fail_on == "blocking" and report["blocking_finding_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
