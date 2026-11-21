"""Tests for the owner-approved model-level price relaxation and proposal updates."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import apply_research_evidence_to_proposals as apply_module
import harvest_model_level_prices as model_harvest

PRICE = ROOT / "docs" / "data-sources" / "price-evidence" / "v1.json"
IDENTITY = ROOT / "docs" / "data-sources" / "identity-map" / "v1.json"
PROPOSAL = ROOT / "docs" / "data-sources" / "proposals" / "nissan.nissan.a02.2018.2887803.json"
CATALOG = ROOT / "catalog" / "variants"


class ModelLevelEvidenceTests(unittest.TestCase):
    def test_documented_price_and_vat_derivation_are_consistent(self):
        data = json.loads(PRICE.read_text(encoding="utf-8"))
        for row in data["entries"]:
            incl = row["purchase_price_incl_vat_eur"]
            expected = round(incl / (1 + row["vat_rate_used"]), 2)
            self.assertEqual(row["purchase_price_excl_vat_eur"], expected)
            self.assertGreater(incl, 0)
            self.assertTrue(row["price"]["match"]["evidence_line"])
            self.assertTrue(row["source_url"].startswith("https://"))
            self.assertEqual(row["market"], "AT")
            self.assertEqual(row["currency"], "EUR")

    def test_no_fabrication_when_no_model_price_exists(self):
        identities = {"entries": [{
            "make": "SKODA", "model": "SKODA", "variant": "X", "powertrain": "ice_diesel",
            "model_year": 2018, "market": "AT", "consumer_model": "Kodiaq",
        }]}
        document, unresolved = model_harvest.build_evidence(identities, {})
        self.assertEqual(document["entries"], [])
        self.assertEqual(unresolved["count"], 1)
        self.assertEqual(unresolved["variants"][0]["reason"], "no_model_level_price_source")

    def test_proposal_update_preserves_every_original_fact(self):
        original = json.loads(PROPOSAL.read_text(encoding="utf-8"))
        identities = {apply_module.proposal_key(original): {
            "consumer_make": "Nissan", "consumer_model": "Leaf 40KWH", "trim": "", "generation": "",
            "source_url": "https://example.invalid/identity", "license": "CC BY 4.0",
            "retrieved_at": "2026-11-21", "reviewed_by": "owner", "confidence": "high",
            "cross_checks": [{"matched": True}],
        }}
        prices = {apply_module.proposal_key(original): {
            "purchase_price_excl_vat_eur": 19151.67, "purchase_price_incl_vat_eur": 22982.0,
            "price_date": "2017-05-01", "currency": "EUR", "market": "AT",
            "source_url": "https://example.invalid/price", "license": "OEM",
            "retrieved_at": "2026-11-21", "price_precision": "model_level",
            "confidence": "low", "tco_ready": False, "catalog_eligible": True,
            "price": {"match": {"uncertainty": "model_level_from_price"}},
        }}
        updated = apply_module.apply(original, identities[apply_module.proposal_key(original)],
                                     prices[apply_module.proposal_key(original)])
        self.assertEqual(updated["identity_quality"], "identity_resolved")
        self.assertIsNone(updated["curation_reason"])
        self.assertFalse(updated["tco_ready"])
        self.assertTrue(updated["catalog_eligible"])
        self.assertFalse(updated["catalog_written"])
        self.assertTrue(updated["requires_owner_approval"])
        self.assertEqual(updated["variant"], original["variant"])
        self.assertEqual(updated["statutory"], original["statutory"])
        self.assertEqual(updated["provenance"], original["provenance"])
        self.assertEqual(updated["deduplication_role"], original["deduplication_role"])
        self.assertEqual(updated["duplicate_of"], original["duplicate_of"])

    def test_committed_proposals_are_updated_and_catalog_untouched(self):
        before = {path.name: path.read_bytes() for path in CATALOG.glob("*.json")}
        proposals = sorted((ROOT / "docs" / "data-sources" / "proposals").glob("*.json"))
        updated = 0
        for path in proposals:
            proposal = json.loads(path.read_text(encoding="utf-8"))
            if proposal.get("identity_quality") == "identity_resolved":
                updated += 1
                self.assertFalse(proposal["catalog_written"])
                self.assertTrue(proposal["requires_owner_approval"])
                self.assertFalse(proposal["tco_ready"])
                self.assertTrue(proposal["catalog_eligible"])
                self.assertEqual(proposal["price_verification"]["price_precision"], "model_level")
                self.assertTrue(proposal["resolved_identity"]["source_url"])
                self.assertTrue(proposal["price_verification"]["source_url"])
        self.assertEqual(updated, 9)
        self.assertEqual({path.name: path.read_bytes() for path in CATALOG.glob("*.json")}, before)


if __name__ == "__main__":
    unittest.main()
