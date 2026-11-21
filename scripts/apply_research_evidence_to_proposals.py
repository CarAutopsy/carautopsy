"""Apply verified research evidence to proposal artifacts (catalog remains untouched).

Only proposals whose exact EEA key has BOTH identity and price evidence are
updated. All EEA source fields, provenance, statutory results, dedup flags,
``catalog_written = false`` and ``requires_owner_approval = true`` are
preserved. Model-level prices remain TCO-ineligible by owner decision.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from harvest_common import write_json

DEFAULT_PROPOSALS = ROOT / "docs" / "data-sources" / "proposals"
DEFAULT_IDENTITY = ROOT / "docs" / "data-sources" / "identity-map" / "v1.json"
DEFAULT_PRICE = ROOT / "docs" / "data-sources" / "price-evidence" / "v1.json"
KEY_FIELDS = ("make", "model", "variant", "powertrain", "model_year", "market")


def index(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {"|".join(str(row[field]) for field in KEY_FIELDS): row for row in entries}


def proposal_key(proposal: dict[str, Any]) -> str:
    variant = proposal["variant"]
    return "|".join(str(part) for part in (
        variant["identity"]["make"],
        variant["identity"]["model"],
        variant["identity"]["variant_name"],
        variant["source_fields"]["powertrain"],
        int(variant["registration"]["first_registration_date"][:4]),
        "AT",
    ))


def apply(proposal: dict[str, Any], identity: dict[str, Any], price: dict[str, Any]) -> dict[str, Any]:
    """Return an updated copy; never mutate the original in place."""
    updated = json.loads(json.dumps(proposal))
    updated["identity_quality"] = "identity_resolved"
    updated["curation_reason"] = None
    updated["resolved_identity"] = {
        "consumer_make": identity["consumer_make"],
        "consumer_model": identity["consumer_model"],
        "trim": identity.get("trim") or None,
        "generation": identity.get("generation") or None,
        "source_url": identity["source_url"],
        "license": identity["license"],
        "retrieved_at": identity["retrieved_at"],
        "reviewed_by": identity["reviewed_by"],
        "confidence": identity.get("confidence"),
        "cross_checks": identity.get("cross_checks", []),
    }
    updated["price_verification"] = {
        "purchase_price_excl_vat_eur": price["purchase_price_excl_vat_eur"],
        "purchase_price_incl_vat_eur": price.get("purchase_price_incl_vat_eur"),
        "price_date": price["price_date"],
        "currency": price["currency"],
        "market": price["market"],
        "source_url": price["source_url"],
        "license": price["license"],
        "retrieved_at": price["retrieved_at"],
        "price_precision": price.get("price_precision", "variant_level"),
        "confidence": price.get("confidence"),
        "tco_ready": bool(price.get("tco_ready", True)),
        "catalog_eligible": bool(price.get("catalog_eligible", True)),
        "price_match": price.get("price", {}).get("match", {}),
    }
    updated["tco_ready"] = bool(price.get("tco_ready", True))
    updated["catalog_eligible"] = bool(price.get("catalog_eligible", True))
    # Keep the original price block consistent with the verified evidence.
    updated["price"]["price_pending"] = False
    updated["price"]["purchase_price_excl_vat_eur"] = price["purchase_price_excl_vat_eur"]
    updated["price"]["price_source"] = price["source_url"]
    updated["price"]["price_source_url"] = price["source_url"]
    updated["catalog_written"] = False
    updated["requires_owner_approval"] = True
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposals", type=Path, default=DEFAULT_PROPOSALS)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--price", type=Path, default=DEFAULT_PRICE)
    args = parser.parse_args()

    identities = index(json.loads(args.identity.resolve().read_text(encoding="utf-8"))["entries"])
    prices = index(json.loads(args.price.resolve().read_text(encoding="utf-8"))["entries"])
    updated_count = 0
    for path in sorted(args.proposals.resolve().glob("*.json")):
        proposal = json.loads(path.read_text(encoding="utf-8"))
        key = proposal_key(proposal)
        identity, price = identities.get(key), prices.get(key)
        if identity is None or price is None:
            continue
        write_json(path, apply(proposal, identity, price))
        updated_count += 1
    print(f"proposals updated: {updated_count} (catalog/variants/ untouched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
