"""Harvest consumer-facing identity evidence for the 57 sampled EEA variants.

Primary evidence is the EEA type-approval source's own commercial-name field
(``Cn``), which is a documented, CC BY 4.0 source fact. Each claim is
cross-checked against the manufacturer's Austrian sitemap (advertised by the
site's robots.txt). If either side is missing, the variant stays unresolved
with an explicit reason. No model, trim or generation is invented.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from harvest_common import (
    fetch_url,
    read_cached_text,
    robots_allows,
    utc_now,
    write_json,
)
from validate_eea_with_adapters import FUEL_MAP, SOURCE_URL, read_rows

DEFAULT_SAMPLE = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2018_wltp_sample.tsv"
DEFAULT_OUTPUT = ROOT / "docs" / "data-sources" / "identity-map" / "v1.json"
DEFAULT_UNRESOLVED = ROOT / "docs" / "data-sources" / "identity-map" / "unresolved.json"
DEFAULT_LOG = ROOT / "docs" / "data-sources" / "harvest-log.json"
LICENSE = "CC BY 4.0 (EEA type-approval microdata)"
REVIEWER = "automated-harvest-v1 (pending owner review)"
SITEMAPS = {
    "NISSAN": "https://www.nissan.at/index.pages-sitemap.xml",
    "SKODA": "https://www.skoda.at/sitemap.xml",
}
WORD_RE = re.compile(r"^[A-Za-z]+$")


def normalize_model(commercial_name: str, make: str) -> str:
    """Normalize a documented commercial name without adding information."""
    value = commercial_name.strip()
    tokens = value.split()
    if tokens and tokens[0].casefold() == make.casefold():
        tokens = tokens[1:]
    cleaned = []
    for token in tokens:
        if WORD_RE.match(token):
            cleaned.append(token[0].upper() + token[1:].lower())
        else:
            cleaned.append(token)
    return " ".join(cleaned)


def load_variants(sample: Path, dataset_year: int) -> list[dict[str, Any]]:
    """Build the 57 exact EEA keys with their source commercial names."""
    variants: dict[tuple[str, str, str, str, int, str], dict[str, Any]] = {}
    for row in read_rows(Path(sample)):
        make = (row.get("Mh") or "Unknown").strip()
        model = (row.get("Mk") or row.get("MMS") or "unknown").strip()
        variant = (row.get("Ve") or row.get("Va") or row.get("T") or "variant").strip()
        fuel = (row.get("Ft") or "").strip().upper()
        powertrain = FUEL_MAP.get(fuel, "")
        market = (row.get("MS") or "").strip()
        key = (make, model, variant, powertrain, dataset_year, market)
        entry = variants.setdefault(key, {
            "make": make,
            "model": model,
            "variant": variant,
            "powertrain": powertrain,
            "model_year": dataset_year,
            "market": market,
            "commercial_name": (row.get("Cn") or "").strip(),
            "eea_record_ids": [],
            "type_approval_numbers": [],
        })
        record_id = (row.get("ID") or "").strip()
        if record_id and record_id not in entry["eea_record_ids"]:
            entry["eea_record_ids"].append(record_id)
        tan = (row.get("TAN") or "").strip()
        if tan and tan not in entry["type_approval_numbers"]:
            entry["type_approval_numbers"].append(tan)
    return sorted(variants.values(), key=lambda item: item["variant"])


def sitemap_check(make: str, model: str) -> dict[str, Any]:
    """Cross-check that the consumer model appears on the OEM Austrian sitemap."""
    sitemap = SITEMAPS.get(make.upper())
    result: dict[str, Any] = {
        "source": sitemap,
        "robots_checked": True,
        "matched": False,
        "matched_url": None,
        "error": None,
    }
    if sitemap is None:
        result["error"] = "no_source_found"
        return result
    if not robots_allows(sitemap):
        result["error"] = "robots_disallowed"
        return result
    meta = fetch_url(sitemap)
    result["retrieved_at"] = meta["retrieved_at"]
    if meta["error"]:
        result["error"] = meta["error"]
        return result
    try:
        text = read_cached_text(meta)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"read_failed: {type(exc).__name__}"
        return result
    token = model.split()[0].casefold() if model else ""
    match = re.search(r"<loc>([^<]*/[^<]*" + re.escape(token) + r"[^<]*)</loc>", text, re.IGNORECASE)
    if match:
        result["matched"] = True
        result["matched_url"] = match.group(1)
    else:
        result["error"] = "model_not_found_in_oem_sitemap"
    return result


def build_evidence(variants: list[dict[str, Any]], dataset_year: int) -> tuple[dict, dict, dict]:
    entries: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    log: list[dict[str, Any]] = []
    harvested_at = utc_now()

    for item in variants:
        key = {
            "make": item["make"],
            "model": item["model"],
            "variant": item["variant"],
            "powertrain": item["powertrain"],
            "model_year": item["model_year"],
            "market": item["market"],
        }
        commercial = item["commercial_name"]
        if not commercial:
            unresolved.append({**key, "reason": "no_source_found", "detail": "EEA Cn field is empty"})
            continue
        if not item["powertrain"]:
            unresolved.append({**key, "reason": "no_source_found", "detail": "EEA fuel code unmapped"})
            continue
        consumer_model = normalize_model(commercial, item["make"])
        if not consumer_model:
            unresolved.append({**key, "reason": "ambiguous", "detail": "Cn contains only the make"})
            continue
        cross_check = sitemap_check(item["make"], consumer_model)
        log.append({
            "variant": item["variant"],
            "source": "oem_sitemap",
            "url": cross_check.get("source"),
            "retrieved_at": cross_check.get("retrieved_at"),
            "matched": cross_check["matched"],
            "error": cross_check["error"],
        })
        if cross_check["error"] == "robots_disallowed":
            unresolved.append({**key, "reason": "tos_blocked", "detail": "OEM robots.txt disallows the sitemap"})
            continue
        confidence = "high" if cross_check["matched"] else "medium"
        entries.append({
            **key,
            "consumer_make": item["make"][0].upper() + item["make"][1:].lower(),
            "consumer_model": consumer_model,
            "trim": "",
            "generation": "",
            "source_url": SOURCE_URL,
            "license": LICENSE,
            "retrieved_at": harvested_at,
            "reviewed_by": REVIEWER,
            "confidence": confidence,
            "evidence": {
                "eea_commercial_name": commercial,
                "eea_record_ids": item["eea_record_ids"],
                "type_approval_numbers": item["type_approval_numbers"],
                "sample_file": str(DEFAULT_SAMPLE.relative_to(ROOT)),
                "dataset_year": dataset_year,
                "mapping": "EEA Cn is the documented consumer/commercial name for this exact variant key",
            },
            "cross_checks": [cross_check],
        })

    document = {
        "schema_version": 1,
        "jurisdiction": "AT",
        "method": "eea_commercial_name_plus_oem_sitemap_crosscheck",
        "dataset_year": dataset_year,
        "harvested_at": harvested_at,
        "entries": entries,
    }
    unresolved_doc = {
        "schema_version": 1,
        "harvested_at": harvested_at,
        "count": len(unresolved),
        "variants": unresolved,
    }
    log_doc = {
        "schema_version": 1,
        "harvested_at": harvested_at,
        "user_agent": "CarAutopsyHarvest/1.0",
        "rate_limit_seconds": 2.0,
        "requests": log,
    }
    return document, unresolved_doc, log_doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--dataset-year", type=int, default=2018)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--unresolved", type=Path, default=DEFAULT_UNRESOLVED)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()

    variants = load_variants(args.sample.resolve(), args.dataset_year)
    document, unresolved, log = build_evidence(variants, args.dataset_year)
    write_json(args.output.resolve(), document)
    write_json(args.unresolved.resolve(), unresolved)
    write_json(args.log.resolve(), log)
    print(
        f"identity harvest: variants={len(variants)} resolved={len(document['entries'])} "
        f"unresolved={unresolved['count']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
