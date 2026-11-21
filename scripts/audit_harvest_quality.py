"""Cross-check harvested evidence and produce a per-variant quality report.

Identity claims require two independent sources (EEA commercial name plus an
OEM sitemap cross-check). Price claims must be dated, fully attributed and
consistent with the EEA variant's powertrain and model year. Single-source
claims and inconsistent prices are flagged, never silently accepted.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from harvest_common import utc_now, write_json
from harvest_identity_evidence import load_variants

DEFAULT_SAMPLE = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2018_wltp_sample.tsv"
DEFAULT_IDENTITY = ROOT / "docs" / "data-sources" / "identity-map" / "v1.json"
DEFAULT_PRICE = ROOT / "docs" / "data-sources" / "price-evidence" / "v1.json"
DEFAULT_OUTPUT = ROOT / "docs" / "data-sources" / "harvest-quality-report.json"
KEY_FIELDS = ("make", "model", "variant", "powertrain", "model_year", "market")
PROVENANCE_FIELDS = ("source_url", "license", "retrieved_at", "confidence")


def load_json(path: Path) -> dict[str, Any]:
    if not Path(path).is_file():
        return {"entries": []}
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))


def index(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {"|".join(str(row[field]) for field in KEY_FIELDS): row for row in entries}


def audit_identity(entry: dict[str, Any] | None, reasons: list[str]) -> dict[str, Any]:
    result = {"present": entry is not None, "sources": 0, "pass": False}
    if entry is None:
        reasons.append("identity_evidence_missing")
        return result
    for field in PROVENANCE_FIELDS:
        if not str(entry.get(field) or "").strip():
            reasons.append(f"identity_missing_{field}")
    sources = 1  # EEA Cn is the primary documented source
    for check in entry.get("cross_checks") or []:
        if isinstance(check, dict) and check.get("matched"):
            sources += 1
    result["sources"] = sources
    if sources < 2:
        reasons.append("identity_single_source_claim")
    if entry.get("confidence") not in {"high", "medium", "low"}:
        reasons.append("identity_invalid_confidence")
    if str(entry.get("consumer_make", "")).casefold() == str(
        entry.get("consumer_model", "")
    ).casefold():
        reasons.append("identity_model_equals_make")
    result["pass"] = not any(reason.startswith("identity_") for reason in reasons)
    return result


def audit_price(
    entry: dict[str, Any] | None,
    eea: dict[str, Any],
    reasons: list[str],
) -> dict[str, Any]:
    result = {"present": entry is not None, "pass": False, "sources": 0}
    if entry is None:
        reasons.append("price_evidence_missing")
        return result
    for field in (*PROVENANCE_FIELDS, "price_date", "currency", "market",
                  "purchase_price_excl_vat_eur"):
        if entry.get(field) in (None, ""):
            reasons.append(f"price_missing_{field}")
    value = entry.get("purchase_price_excl_vat_eur")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        reasons.append("price_invalid_amount")
    year = int(eea["model_year"])
    try:
        price_year = date.fromisoformat(str(entry.get("price_date") or "")).year
    except ValueError:
        reasons.append("price_invalid_date")
    else:
        if price_year not in (year - 1, year, year + 1):
            reasons.append("price_date_outside_model_year_window")
    if str(entry.get("market") or "").upper() != "AT":
        reasons.append("price_wrong_market")
    if str(entry.get("currency") or "").upper() != "EUR":
        reasons.append("price_wrong_currency")
    evidence = str(entry.get("price_match_evidence") or "")
    if entry["powertrain"] == "bev" and "kwh" not in evidence.lower():
        reasons.append("price_powertrain_not_corroborated")
    result["sources"] = 1 if entry.get("source_url") else 0
    result["pass"] = not any(reason.startswith("price_") for reason in reasons)
    return result


def build_report(sample: Path, identity_path: Path, price_path: Path) -> dict[str, Any]:
    variants = load_variants(sample, 2018)
    identity_index = index(load_json(identity_path).get("entries", []))
    price_index = index(load_json(price_path).get("entries", []))
    rows: list[dict[str, Any]] = []
    for item in variants:
        key = "|".join(str(item[field]) for field in KEY_FIELDS)
        reasons: list[str] = []
        identity = audit_identity(identity_index.get(key), reasons)
        price = audit_price(price_index.get(key), item, reasons)
        rows.append({
            "variant": item["variant"],
            "make": item["make"],
            "model": item["model"],
            "powertrain": item["powertrain"],
            "identity": identity,
            "price": price,
            "gate_ready": identity["pass"] and price["pass"],
            "reasons": reasons,
        })
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "checked_variants": len(rows),
        "identity_pass_count": sum(1 for row in rows if row["identity"]["pass"]),
        "price_pass_count": sum(1 for row in rows if row["price"]["pass"]),
        "gate_ready_count": sum(1 for row in rows if row["gate_ready"]),
        "single_source_identity_count": sum(
            1 for row in rows if "identity_single_source_claim" in row["reasons"]
        ),
        "variants": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--price", type=Path, default=DEFAULT_PRICE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.sample.resolve(), args.identity.resolve(), args.price.resolve())
    write_json(args.output.resolve(), report)
    print(
        f"harvest audit: checked={report['checked_variants']} "
        f"identity_pass={report['identity_pass_count']} "
        f"price_pass={report['price_pass_count']} "
        f"gate_ready={report['gate_ready_count']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
