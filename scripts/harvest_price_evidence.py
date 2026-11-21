"""Harvest dated Austrian price evidence for the 57 sampled EEA variants.

Sources attempted: publicly accessible Wayback Machine snapshots of Austrian
OEM price lists, discovered through the CDX index. A price is accepted only
when the PDF text ties a positive, dated price to the *exact* EEA variant code
or record id. Model-level "from" prices and incl-VAT brochure prices are never
accepted. Missing evidence is recorded as an explicit reason.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
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
from harvest_identity_evidence import load_variants

DEFAULT_SAMPLE = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2018_wltp_sample.tsv"
DEFAULT_OUTPUT = ROOT / "docs" / "data-sources" / "price-evidence" / "v1.json"
DEFAULT_UNRESOLVED = ROOT / "docs" / "data-sources" / "price-evidence" / "unresolved.json"
DEFAULT_LOG = ROOT / "docs" / "data-sources" / "harvest-price-log.json"
LICENSE = "OEM price list (public archived snapshot); terms: see source URL"
REVIEWER = "automated-harvest-v1 (pending owner review)"
CDX = (
    "https://web.archive.org/cdx/search/cdx?url={host}/*&from=2017&to=2019"
    "&output=json&filter=statuscode:200&filter=mimetype:application/pdf"
    "&collapse=urlkey&limit=25"
)
HOSTS = ("www.skoda.at", "www.nissan.at")
PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*)(?:,(\d{2}))?")


def parse_price(text: str) -> float | None:
    """Parse an Austrian formatted price into a finite positive EUR number."""
    if not isinstance(text, str):
        return None
    match = PRICE_RE.fullmatch(text.strip().replace("\xa0", "").replace(" ", ""))
    if match is None:
        return None
    value = float(match.group(1).replace(".", "") + ("." + match.group(2) if match.group(2) else ""))
    return value if value > 0 else None


def validate_price_row(row: dict[str, Any]) -> list[str]:
    """Return a list of reasons why a candidate price row is not acceptable."""
    reasons: list[str] = []
    price = row.get("purchase_price_excl_vat_eur")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        reasons.append("invalid_price")
    try:
        date.fromisoformat(str(row.get("price_date") or ""))
    except ValueError:
        reasons.append("invalid_price_date")
    if str(row.get("currency") or "").upper() != "EUR":
        reasons.append("invalid_currency")
    if str(row.get("market") or "").upper() != "AT":
        reasons.append("invalid_market")
    for field in ("source_url", "license", "retrieved_at"):
        if not str(row.get(field) or "").strip():
            reasons.append(f"missing_{field}")
    return reasons


def discover_snapshots() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """List archived OEM price-list PDFs; return (candidates, request log)."""
    candidates: list[dict[str, Any]] = []
    log: list[dict[str, Any]] = []
    for host in HOSTS:
        url = CDX.format(host=host)
        if not robots_allows(url):
            log.append({"host": host, "url": url, "error": "robots_disallowed"})
            continue
        meta = fetch_url(url)
        log.append({
            "host": host,
            "url": url,
            "retrieved_at": meta["retrieved_at"],
            "status": meta["status"],
            "error": meta["error"],
        })
        if meta["error"]:
            continue
        try:
            rows: list[list[str]] = json.loads(read_cached_text(meta))
        except Exception:  # noqa: BLE001
            log.append({"host": host, "url": url, "error": "unparseable_cdx"})
            continue
        for record in rows[1:]:
            if len(record) < 6:
                continue
            original, timestamp = record[2], record[1]
            lowered = original.lower()
            # "Streuer" are Austrian tax guides that also publish list-price tables.
            if not any(token in lowered for token in ("preisliste", "price", "streuer")):
                continue
            snapshot = f"https://web.archive.org/web/{timestamp}id_/{original}"
            candidates.append({
                "host": host,
                "original": original,
                "timestamp": timestamp,
                "snapshot_url": snapshot,
                "date": f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}",
            })
    return candidates, log


def _extract_pdfplumber(path: str) -> str:
    """Primary extractor: pdfplumber/pdfminer."""
    import pdfplumber

    with pdfplumber.open(path) as document:
        return "\n".join((page.extract_text() or "") for page in document.pages)


def _extract_pymupdf(path: str) -> str:
    """Fallback for damaged or partly truncated PDFs: PyMuPDF."""
    import pymupdf

    with pymupdf.open(path) as document:
        return "\n".join(page.get_text() for page in document)


def _extract_ocr(path: str) -> str:
    """Last resort for scanned pages: render with PyMuPDF, OCR with pytesseract."""
    import io

    import pymupdf
    import pytesseract
    from PIL import Image

    chunks: list[str] = []
    with pymupdf.open(path) as document:
        for page in document:
            pixmap = page.get_pixmap()
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            chunks.append(pytesseract.image_to_string(image, lang="eng"))
    return "\n".join(chunks)


EXTRACTORS = (
    ("pdfplumber", _extract_pdfplumber),
    ("pymupdf", _extract_pymupdf),
    ("ocr", _extract_ocr),
)


def extract_text(snapshot: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract PDF text with a pdfplumber -> PyMuPDF -> OCR fallback chain.

    A failed extractor is recorded, never guessed. An empty result means no
    verifiable text could be recovered from the archived snapshot.
    """
    meta = fetch_url(snapshot["snapshot_url"])
    if meta["error"] or not meta.get("cache_path"):
        return "", meta
    attempts: list[str] = []
    for name, extractor in EXTRACTORS:
        try:
            text = extractor(meta["cache_path"])
        except ImportError as exc:
            attempts.append(f"{name}:unavailable({str(exc)[:40]})")
            continue
        except Exception as exc:  # noqa: BLE001 - recorded, never guessed
            attempts.append(f"{name}:{type(exc).__name__}")
            continue
        if text and text.strip():
            meta["extractor"] = name
            meta["error"] = None
            return text, meta
        attempts.append(f"{name}:no_text")
    meta["error"] = "all_extractors_failed: " + "; ".join(attempts)
    return "", meta


def build_evidence(variants: list[dict[str, Any]]) -> tuple[dict, dict, dict]:
    harvested_at = utc_now()
    candidates, discovery_log = discover_snapshots()
    texts: list[tuple[dict[str, Any], str]] = []
    for snapshot in candidates[:4]:  # bounded: never hammer the archive
        text, meta = extract_text(snapshot)
        discovery_log.append({
            "snapshot_url": snapshot["snapshot_url"],
            "retrieved_at": meta["retrieved_at"],
            "status": meta["status"],
            "error": meta["error"],
            "text_chars": len(text),
        })
        if text:
            texts.append((snapshot, text))

    entries: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for item in variants:
        key = {
            "make": item["make"],
            "model": item["model"],
            "variant": item["variant"],
            "powertrain": item["powertrain"],
            "model_year": item["model_year"],
            "market": item["market"],
        }
        match_snapshot = None
        match_line = None
        for snapshot, text in texts:
            for line in text.splitlines():
                if item["variant"] in line or (
                    item["eea_record_ids"] and item["eea_record_ids"][0] in line
                ):
                    match_snapshot, match_line = snapshot, line
                    break
            if match_snapshot:
                break
        if match_snapshot is None:
            unresolved.append({
                **key,
                "reason": "no_variant_level_price_in_source",
                "detail": (
                    "No archived price document ties a dated price to this exact "
                    "EEA variant code; model-level list prices were not accepted"
                ),
                "candidates_checked": len(texts),
            })
            continue
        numbers = [parse_price(token) for token in match_line.split()]
        prices = [value for value in numbers if value is not None]
        if len(prices) != 1:
            unresolved.append({**key, "reason": "ambiguous_price", "detail": match_line[:200]})
            continue
        candidate = {
            **key,
            "purchase_price_excl_vat_eur": prices[0],
            "price_date": match_snapshot["date"],
            "currency": "EUR",
            "market": "AT",
            "source_url": match_snapshot["snapshot_url"],
            "license": LICENSE,
            "retrieved_at": harvested_at,
            "reviewed_by": REVIEWER,
            "confidence": "medium",
        }
        problems = validate_price_row(candidate)
        if problems:
            unresolved.append({**key, "reason": "invalid_price", "detail": ", ".join(problems)})
            continue
        candidate["price_match_evidence"] = match_line[:300]
        entries.append(candidate)

    document = {
        "schema_version": 1,
        "jurisdiction": "AT",
        "method": "wayback_oem_price_list_exact_variant_match",
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
        "candidates": candidates,
        "requests": discovery_log,
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
    document, unresolved, log = build_evidence(variants)
    write_json(args.output.resolve(), document)
    write_json(args.unresolved.resolve(), unresolved)
    write_json(args.log.resolve(), log)
    print(
        f"price harvest: variants={len(variants)} verified={len(document['entries'])} "
        f"unresolved={unresolved['count']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
