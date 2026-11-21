"""Exhaustive, robots-respecting Wayback search for Kodiaq/Karoq price evidence.

Broadens the original CDX query: no mimetype filter, 100 results per query,
six URL patterns, two time windows. Downloads are bounded and cached only in
the system temp directory; no raw crawl dump is written to the repository.
Any price claim must come from a real snapshot with full provenance.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from harvest_common import fetch_url, read_cached_text, robots_allows
from harvest_model_level_prices import first_from_price
from harvest_price_evidence import extract_text

PATTERNS = (
    "www.skoda.at/kodiaq*",
    "www.skoda.at/karoq*",
    "www.skoda.at/modelle/kodiaq*",
    "www.skoda.at/modelle/karoq*",
    "www.skoda.at/preisliste*",
    "www.skoda.at/preise*",
)
WINDOWS = ((2017, 2017), (2018, 2019))
CDX = (
    "https://web.archive.org/cdx/search/cdx?url={pattern}&from={start}&to={end}"
    "&output=json&filter=statuscode:200&limit=100"
)
PRICE_HEADER = re.compile(r"PREISE\s+(KODIAQ|KAROQ)", re.IGNORECASE)
MAX_EXTRACTIONS = 15
PREFER_TOKENS = ("preis", "streuer", "kodiaq", "karoq")


BROAD_QUERIES = (
    (
        "www.skoda.at/* (no mimetype filter)",
        (
            "https://web.archive.org/cdx/search/cdx?url=www.skoda.at/*&from={start}&to={end}"
            "&output=json&filter=statuscode:200&limit=300"
        ),
    ),
    (
        "www.skoda.at/* (PDF only)",
        (
            "https://web.archive.org/cdx/search/cdx?url=www.skoda.at/*&from={start}&to={end}"
            "&output=json&filter=statuscode:200&filter=mimetype:application/pdf"
            "&collapse=urlkey&limit=60"
        ),
    ),
)


def cdx_queries() -> list[dict[str, Any]]:
    specs = [
        (pattern, f"{start}-{end}", CDX.format(pattern=pattern, start=start, end=end))
        for pattern in PATTERNS
        for start, end in WINDOWS
    ]
    specs.extend(
        (label, f"{start}-{end}", template.format(start=start, end=end))
        for label, template in BROAD_QUERIES
        for start, end in WINDOWS
    )
    queries: list[dict[str, Any]] = []
    for pattern, window, url in specs:
        entry: dict[str, Any] = {
            "pattern": pattern,
            "window": window,
            "url": url,
            "robots_allowed": robots_allows(url),
            "snapshots": 0,
            "error": None,
        }
        if not entry["robots_allowed"]:
            entry["error"] = "robots_disallowed"
            queries.append(entry)
            continue
        meta = fetch_url(url)
        entry["retrieved_at"] = meta.get("retrieved_at")
        if meta["error"]:
            entry["error"] = meta["error"]
            queries.append(entry)
            continue
        try:
            rows: list[list[str]] = json.loads(read_cached_text(meta))
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"unparseable_cdx:{type(exc).__name__}"
            queries.append(entry)
            continue
        snapshots = []
        for record in rows[1:]:
            if len(record) < 6:
                continue
            snapshots.append({
                "timestamp": record[1],
                "original": record[2],
                "mimetype": record[3],
                "statuscode": record[4],
                "snapshot_url": f"https://web.archive.org/web/{record[1]}id_/{record[2]}",
            })
        entry["snapshots"] = len(snapshots)
        entry["rows"] = snapshots
        queries.append(entry)
    return queries


def select_candidates(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for query in queries:
        for snapshot in query.get("rows", []):
            original = snapshot["original"]
            if original in seen:
                continue
            seen.add(original)
            lower = original.lower()
            score = sum(1 for token in PREFER_TOKENS if token in lower)
            if snapshot["mimetype"] == "application/pdf":
                score += 1
            candidate = dict(snapshot)
            candidate["score"] = score
            candidates.append(candidate)
    candidates.sort(key=lambda item: (-item["score"], item["original"]))
    return candidates


def inspect(snapshot: dict[str, Any]) -> dict[str, Any]:
    text, meta = extract_text(snapshot)
    result: dict[str, Any] = {
        "original": snapshot["original"],
        "snapshot_url": snapshot["snapshot_url"],
        "mimetype": snapshot["mimetype"],
        "retrieved_at": meta.get("retrieved_at"),
        "extractor": meta.get("extractor"),
        "error": meta.get("error"),
        "text_chars": len(text),
        "price_header_found": False,
        "price": None,
        "evidence_line": None,
    }
    if not text:
        return result
    result["price_header_found"] = bool(PRICE_HEADER.search(text))
    if not result["price_header_found"]:
        return result
    price, evidence = first_from_price(text)
    if price is not None:
        result["price"] = price
        result["evidence_line"] = evidence
    return result


def run(output: Path) -> dict[str, Any]:
    queries = cdx_queries()
    candidates = select_candidates(queries)
    inspections = [inspect(candidate) for candidate in candidates[:MAX_EXTRACTIONS]]
    matches = [item for item in inspections if item["price"] is not None]
    summary = {
        "schema_version": 1,
        "queries": [
            {key: value for key, value in query.items() if key != "rows"}
            for query in queries
        ],
        "queries_attempted": len(queries),
        "queries_succeeded": sum(1 for query in queries if not query["error"]),
        "snapshots_found": sum(query["snapshots"] for query in queries),
        "unique_snapshots": len(candidates),
        "snapshots_extracted": len(inspections),
        "extraction_successes": sum(1 for item in inspections if item["text_chars"] > 0),
        "price_headers_found": sum(1 for item in inspections if item["price_header_found"]),
        "prices_found": len(matches),
        "inspections": inspections,
        "matches": matches,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.output.resolve())
    print(
        f"queries={summary['queries_attempted']} succeeded={summary['queries_succeeded']} "
        f"snapshots={summary['snapshots_found']} unique={summary['unique_snapshots']} "
        f"extracted={summary['snapshots_extracted']} "
        f"text_ok={summary['extraction_successes']} "
        f"headers={summary['price_headers_found']} prices={summary['prices_found']} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
