"""Research-only coverage report for identity and price resolution.

Reads the committed, sampled EEA TSV (never a full corpus), applies *optional*
versioned identity-map and price-evidence files, and reports how many sampled
records could be identity-resolved, price-verified and fully gate-ready. It
never writes to ``catalog/variants/``, never mutates proposals, never retrieves
data and never invents an identity or price: absent or incomplete evidence is
reported as zero coverage with an explicit reason.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from validate_eea_with_adapters import (
    DEFAULT_STATUTORY_RULES,
    evaluate_identity_quality,
    evaluate_statutory,
    is_wltp_era,
    load_statutory_rules,
    map_row,
    read_rows,
)
from validate_tco_readiness import validate_variant_readiness

DEFAULT_SAMPLE = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2018_wltp_sample.tsv"
DEFAULT_IDENTITY_MAP = ROOT / "docs" / "data-sources" / "identity-map" / "v1.json"
DEFAULT_PRICE_EVIDENCE = ROOT / "docs" / "data-sources" / "price-evidence" / "v1.json"
DEFAULT_OUTPUT = ROOT / "docs" / "data-sources" / "research-coverage-report.json"
REPORT_DATE = "2026-11-21"
SCHEMA_VERSION = 1

IDENTITY_ROW_FIELDS = (
    "consumer_make", "consumer_model", "trim", "generation", "source_url",
    "license", "retrieved_at", "reviewed_by",
)
PRICE_ROW_FIELDS = (
    "purchase_price_excl_vat_eur", "price_date", "currency", "market",
    "source_url", "license", "retrieved_at",
)
KEY_FIELDS = ("make", "model", "variant", "powertrain", "model_year", "market")


class ResearchReportError(ValueError):
    """Explicit failure for unsafe output paths or malformed evidence."""


def assert_report_output_safe(path: Path) -> Path:
    """Resolve the output path and reject any location inside the catalog."""
    resolved = path.resolve()
    for catalog in (ROOT / "catalog",):
        if resolved == catalog.resolve() or resolved.is_relative_to(catalog.resolve()):
            raise ResearchReportError("report output must not overlap the catalog directory")
    return resolved


def load_evidence(path: Path | None) -> tuple[dict[str, Any], bool]:
    """Return (entries-by-key, file-exists). Missing evidence is not an error."""
    if path is None or not Path(path).is_file():
        return {}, False
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ResearchReportError("evidence file must be a version 1 JSON object")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ResearchReportError("evidence file has no entries list")
    indexed: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or any(field not in entry for field in KEY_FIELDS):
            raise ResearchReportError("evidence entry is missing a key field")
        key = "|".join(str(entry[field]) for field in KEY_FIELDS)
        indexed[key] = entry
    return indexed, True


def key_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Build the exact match key from the record's identity and source fields."""
    identity = record.get("identity") or {}
    source = record.get("source_fields") or {}
    registered = record.get("registration", {}).get("first_registration_date", "")
    year = int(str(registered)[:4]) if str(registered)[:4].isdigit() else None
    return {
        "make": str(identity.get("make") or ""),
        "model": str(identity.get("model") or ""),
        "variant": str(identity.get("variant_name") or ""),
        "powertrain": str(source.get("powertrain") or ""),
        "model_year": year,
        "market": "AT",
    }


def missing_fields(row: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    """Return required fields that are absent, blank or not positive numbers."""
    missing: list[str] = []
    for field in fields:
        value = row.get(field)
        if field == "purchase_price_excl_vat_eur":
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                missing.append(field)
        elif value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def enrich_record(
    record: dict[str, Any],
    identity_row: dict[str, Any] | None,
    price_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a copy with verified evidence applied; never mutates the input."""
    enriched = copy.deepcopy(record)
    if identity_row is not None:
        enriched["identity"]["make"] = identity_row["consumer_make"]
        enriched["identity"]["model"] = identity_row["consumer_model"]
        # The resolved consumer trim replaces the EEA approval code for display;
        # the original code stays in source_fields for audit.
        enriched["identity"]["variant_name"] = identity_row["trim"]
        enriched["identity"]["trim"] = identity_row["trim"]
        enriched["identity"]["generation"] = identity_row["generation"]
        enriched["identity"]["resolution"] = {
            "method": "curated_mapping",
            "source_url": identity_row["source_url"],
            "license": identity_row["license"],
            "retrieved_at": identity_row["retrieved_at"],
            "matched_fields": KEY_FIELDS,
            "reviewed_by": identity_row["reviewed_by"],
        }
    if price_row is not None:
        offer = enriched.setdefault("offers", [{}])[0]
        for field in PRICE_ROW_FIELDS:
            offer[field] = price_row[field]
        offer["uncertainty"] = "none"
        enriched["price_pending"] = False
    return enriched


def analyze_sample(
    *,
    sample: Path = DEFAULT_SAMPLE,
    dataset_year: int = 2018,
    identity_map: Path | None = DEFAULT_IDENTITY_MAP,
    price_evidence: Path | None = DEFAULT_PRICE_EVIDENCE,
    as_of: str = REPORT_DATE,
) -> dict[str, Any]:
    """Compute identity/price/full-gate coverage over the sampled TSV only."""
    rules = load_statutory_rules(DEFAULT_STATUTORY_RULES)
    identities, identity_present = load_evidence(identity_map)
    prices, price_present = load_evidence(price_evidence)
    rows = read_rows(Path(sample))
    records = [map_row(row, dataset_year, None) for row in rows]

    identity_reasons: Counter[str] = Counter()
    price_reasons: Counter[str] = Counter()
    identity_ok = price_ok = gate_ready = statutory_verified = 0
    baseline_gate_pass = 0
    resolved_variants: list[str] = []
    priced_variants: list[str] = []
    ready_variants: list[str] = []

    for record in records:
        key = key_fields(record)
        key_string = "|".join(str(key[field]) for field in KEY_FIELDS)
        registered_raw = record.get("registration", {}).get("first_registration_date", "")
        registered = date.fromisoformat(registered_raw)

        # Baseline statutory + structural readiness, before research evidence.
        statutory = evaluate_statutory(record, rules, registered)
        record["statutory"] = statutory
        if statutory["verified"]:
            statutory_verified += 1
        wltp_ok = is_wltp_era(dataset_year)
        if wltp_ok and statutory["verified"] and not validate_variant_readiness(
            record, statutory["taxes"]
        ):
            baseline_gate_pass += 1

        identity_row = identities.get(key_string)
        if not identity_present:
            identity_reasons["no_identity_evidence_file"] += 1
        elif identity_row is None:
            identity_reasons["no_exact_identity_mapping_row"] += 1
        elif missing_fields(identity_row, IDENTITY_ROW_FIELDS):
            identity_reasons["incomplete_identity_mapping_row"] += 1
        else:
            identity_ok += 1
            resolved_variants.append(str(record.get("variant_id")))

        price_row = prices.get(key_string)
        if not price_present:
            price_reasons["no_price_evidence_file"] += 1
        elif price_row is None:
            price_reasons["no_exact_price_row"] += 1
        elif missing_fields(price_row, PRICE_ROW_FIELDS):
            price_reasons["incomplete_price_row"] += 1
        else:
            price_ok += 1
            priced_variants.append(str(record.get("variant_id")))

        if identity_row is None or price_row is None:
            continue
        if missing_fields(identity_row, IDENTITY_ROW_FIELDS) or missing_fields(
            price_row, PRICE_ROW_FIELDS
        ):
            continue
        enriched = enrich_record(record, identity_row, price_row)
        enriched_statutory = evaluate_statutory(enriched, rules, registered)
        if (
            wltp_ok
            and enriched_statutory["verified"]
            and evaluate_identity_quality(enriched)["identity_quality"] == "ok"
            and not validate_variant_readiness(enriched, enriched_statutory["taxes"])
        ):
            gate_ready += 1
            ready_variants.append(str(record.get("variant_id")))

    total = len(records)

    def percentage(count: int) -> float:
        return round(100 * count / total, 1) if total else 0.0

    return {
        "schema_version": SCHEMA_VERSION,
        "report_date": as_of,
        "sample_file": Path(sample).relative_to(ROOT).as_posix() if Path(sample).is_relative_to(ROOT) else str(sample),
        "dataset_year": dataset_year,
        "sampled_only": True,
        "sampled": total,
        "identity": {
            "approach": "curated_mapping",
            "evidence_file": Path(identity_map).relative_to(ROOT).as_posix() if identity_map and Path(identity_map).is_relative_to(ROOT) else str(identity_map),
            "evidence_available": identity_present,
            "evidence_rows": len(identities),
            "resolvable": identity_ok,
            "resolvable_pct": percentage(identity_ok),
            "reasons": dict(sorted(identity_reasons.items())),
            "resolved_variant_ids": sorted(set(resolved_variants)),
        },
        "price": {
            "approach": "curated_price_evidence",
            "compliant_bulk_source_available": False,
            "evidence_file": Path(price_evidence).relative_to(ROOT).as_posix() if price_evidence and Path(price_evidence).is_relative_to(ROOT) else str(price_evidence),
            "evidence_available": price_present,
            "evidence_rows": len(prices),
            "verified": price_ok,
            "verified_pct": percentage(price_ok),
            "reasons": dict(sorted(price_reasons.items())),
            "priced_variant_ids": sorted(set(priced_variants)),
        },
        "gate_ready_after_resolution": {
            "count": gate_ready,
            "pct": percentage(gate_ready),
            "variant_ids": sorted(set(ready_variants)),
            "prerequisites": [
                "identity_resolved", "price_verified", "statutory_verified",
                "wltp_era", "structural_readiness",
            ],
        },
        "baseline": {
            "statutory_verified": statutory_verified,
            "readiness_gate_passing_before_research": baseline_gate_pass,
            "distinct_variant_codes": len({record["identity"]["variant_name"] for record in records}),
            "identity_quality_ok_before_research": sum(
                1 for record in records
                if evaluate_identity_quality(record)["identity_quality"] == "ok"
            ),
        },
        "catalog_variants_written": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--dataset-year", type=int, default=2018)
    parser.add_argument("--identity-map", type=Path, default=DEFAULT_IDENTITY_MAP)
    parser.add_argument("--price-evidence", type=Path, default=DEFAULT_PRICE_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    report = analyze_sample(
        sample=args.sample.resolve(),
        dataset_year=args.dataset_year,
        identity_map=args.identity_map.resolve(),
        price_evidence=args.price_evidence.resolve(),
    )
    output = assert_report_output_safe(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"sample={report['sample_file']} sampled={report['sampled']} "
        f"identity_resolvable={report['identity']['resolvable']} "
        f"price_verified={report['price']['verified']} "
        f"gate_ready={report['gate_ready_after_resolution']['count']} "
        f"catalog_variants_written=0 report={output}"
    )
    if args.stdout:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
