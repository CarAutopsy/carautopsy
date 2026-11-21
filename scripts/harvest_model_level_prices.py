"""Owner-approved interim model-level price evidence for sampled EEA variants.

The owner explicitly approved accepting dated, attributed model-level "from"
prices where no variant-level price exists. Such rows are marked
``price_precision = "model_level"``, ``confidence = "low"``,
``tco_ready = false`` and ``catalog_eligible = true``. Prices are parsed from
real archived Austrian OEM price-list PDFs discovered by the price harvester;
nothing is invented. The raw evidence line and validity date are retained.
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

from harvest_common import utc_now, write_json
from harvest_price_evidence import extract_text, parse_price

DEFAULT_PRICE_LOG = ROOT / "docs" / "data-sources" / "harvest-price-log.json"
DEFAULT_IDENTITY = ROOT / "docs" / "data-sources" / "identity-map" / "v1.json"
DEFAULT_OUTPUT = ROOT / "docs" / "data-sources" / "price-evidence" / "v1.json"
DEFAULT_UNRESOLVED = ROOT / "docs" / "data-sources" / "price-evidence" / "unresolved.json"
KEY_FIELDS = ("make", "model", "variant", "powertrain", "model_year", "market")
VAT_RATE = 0.20
LICENSE = "OEM price list, public archived snapshot; terms per source publisher"
REVIEWER = "automated-model-level-harvest-v1 (pending owner review)"
PRICE_TOKEN = re.compile(r"(\d{1,3}\.\d{3}),\D")
DATE_TOKEN = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "maerz": 3, "marz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11,
    "dezember": 12,
}
KNOWN_MODELS = ("leaf", "octavia", "superb", "rapid", "fabia", "karoq", "kodiaq")


def ascii_german(line: str) -> str:
    """Transliterate German umlauts before ASCII folding for date matching."""
    normalized = line
    for source, target in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"),
                           ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue")):
        normalized = normalized.replace(source, target)
    return normalized.encode("ascii", "replace").decode().lower()


def validity_date(text: str, fallback: str) -> tuple[str, str]:
    """Return (ISO date, precision) from the document, else the snapshot date."""
    for line in text.splitlines():
        if not re.search(r"g.ltig ab", line, re.IGNORECASE):
            continue
        found = DATE_TOKEN.search(line)
        if found:
            day, month, year = (int(part) for part in found.groups())
            try:
                return date(year, month, day).isoformat(), "day"
            except ValueError:
                continue
        ascii_line = ascii_german(line)
        for name, month in GERMAN_MONTHS.items():
            match = re.search(r"(\d{1,2})\.\s*" + name + r"\s+(\d{4})", ascii_line)
            if match:
                day, year = int(match.group(1)), int(match.group(2))
                try:
                    return date(year, month, day).isoformat(), "day"
                except ValueError:
                    continue
    # Edition lines such as "Ausgabe: Oesterreich, Maerz 2019" give month only.
    for line in text.splitlines():
        ascii_line = ascii_german(line)
        if "ausgabe" not in ascii_line:
            continue
        for name, month in GERMAN_MONTHS.items():
            match = re.search(name + r"\s+(\d{4})", ascii_line)
            if match:
                return date(int(match.group(1)), month, 1).isoformat(), "month"
    return fallback, "snapshot"


def first_from_price(text: str) -> tuple[float | None, str | None]:
    """Return the first documented price in a model/trim table row.

    Some PDFs place the engine label and the price on separate lines, so a
    small rolling window is used and the full matched window is retained as
    evidence.
    """
    lines = text.splitlines()
    # OEM tables describe engine rows either by "PS" (Skoda) or by "kWh" (BEV).
    for marker in ("ps", "kwh"):
        for index, line in enumerate(lines):
            if marker not in line.lower():
                continue
            window = lines[index:index + 5]
            for candidate_line in window:
                match = PRICE_TOKEN.search(candidate_line)
                if match is None:
                    continue
                price = parse_price(match.group(1))
                if price is not None and price > 0:
                    evidence = " | ".join(part.strip() for part in window if part.strip())
                    return price, evidence[:300]
    return None, None


def discover_model_prices(price_log: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Extract one dated model-level 'from' price per archived OEM price list."""
    models: dict[str, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []
    for candidate in price_log.get("candidates", []):
        filename = candidate.get("original", "").split("/")[-1].lower()
        model = next((name for name in KNOWN_MODELS if name in filename), None)
        if model is None:
            continue
        text, meta = extract_text(candidate)
        attempt: dict[str, Any] = {
            "model": model,
            "snapshot_url": candidate["snapshot_url"],
            "retrieved_at": meta.get("retrieved_at"),
            "status": meta.get("status"),
            "error": meta.get("error"),
            "text_chars": len(text),
        }
        if not text:
            attempts.append(attempt)
            continue
        if model not in text.lower():
            attempt["error"] = "model_not_corroborated_in_text"
            attempts.append(attempt)
            continue
        price, evidence_line = first_from_price(text)
        if price is None:
            attempt["error"] = "no_parseable_model_price"
            attempts.append(attempt)
            continue
        attempt.update(price_incl_vat=price, evidence_line=evidence_line[:300])
        attempts.append(attempt)
        # Keep the most recent validity date for a given model.
        price_date, date_precision = validity_date(text, candidate["date"])
        existing = models.get(model)
        if existing is None or price_date > existing["price_date"]:
            models[model] = {
                "model": model,
                "price_incl_vat": price,
                "price_date": price_date,
                "price_date_precision": date_precision,
                "source_url": candidate["snapshot_url"],
                "evidence_line": evidence_line[:300],
                "retrieved_at": meta["retrieved_at"],
                "extractor": meta.get("extractor"),
            }
    return models, attempts


def model_token(consumer_model: str) -> str:
    return consumer_model.strip().split()[0].casefold() if consumer_model.strip() else ""


def build_evidence(
    identities: dict[str, Any],
    models: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    harvested_at = utc_now()
    entries: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in identities.get("entries", []):
        key = {field: row[field] for field in KEY_FIELDS}
        candidate = models.get(model_token(str(row.get("consumer_model") or "")))
        if candidate is None:
            unresolved.append({
                **key,
                "reason": "no_model_level_price_source",
                "detail": "No dated archived AT price list found for this consumer model",
            })
            continue
        incl = float(candidate["price_incl_vat"])
        excl = round(incl / (1 + VAT_RATE), 2)
        entries.append({
            **key,
            "purchase_price_excl_vat_eur": excl,
            "purchase_price_incl_vat_eur": incl,
            "price_date": candidate["price_date"],
            "price_date_precision": candidate.get("price_date_precision", "snapshot"),
            "currency": "EUR",
            "market": "AT",
            "source_url": candidate["source_url"],
            "license": LICENSE,
            "retrieved_at": candidate["retrieved_at"] or harvested_at,
            "reviewed_by": REVIEWER,
            "price_pending": False,
            "price_precision": "model_level",
            "confidence": "low",
            "tco_ready": False,
            "catalog_eligible": True,
            "vat_rate_used": VAT_RATE,
            "vat_treatment": "source list price stated incl. VAT; excl-VAT value derived arithmetically",
            "nova_treatment": "Austrian OEM list prices may include NoVA; not separately removed",
            "price": {
                "price_pending": False,
                "match": {
                    "matched_model": candidate["model"],
                    "matched_fields": ("consumer_model", "market", "model_year_window"),
                    "uncertainty": "model_level_from_price; not variant-specific",
                    "evidence_line": candidate["evidence_line"],
                },
            },
        })
    document = {
        "schema_version": 1,
        "jurisdiction": "AT",
        "method": "owner_approved_model_level_archived_oem_price",
        "harvested_at": harvested_at,
        "notice": (
            "Interim owner-approved relaxation: model-level 'from' prices are "
            "catalog-eligible but not TCO-ready (price_precision=model_level, "
            "confidence=low, tco_ready=false)."
        ),
        "entries": entries,
    }
    unresolved_doc = {
        "schema_version": 1,
        "harvested_at": harvested_at,
        "count": len(unresolved),
        "variants": unresolved,
    }
    return document, unresolved_doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-log", type=Path, default=DEFAULT_PRICE_LOG)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--unresolved", type=Path, default=DEFAULT_UNRESOLVED)
    args = parser.parse_args()

    price_log = json.loads(args.price_log.resolve().read_text(encoding="utf-8"))
    identities = json.loads(args.identity.resolve().read_text(encoding="utf-8"))
    models, attempts = discover_model_prices(price_log)
    document, unresolved = build_evidence(identities, models)
    write_json(args.output.resolve(), document)
    write_json(args.unresolved.resolve(), unresolved)
    print(
        f"model-level price harvest: models={sorted(models)} "
        f"keys={len(document['entries'])} unresolved={unresolved['count']} "
        f"output={args.output}"
    )
    for attempt in attempts:
        print(f"  {attempt['model']}: chars={attempt['text_chars']} error={attempt['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
