"""Tests for the owner-approved model-level price relaxation and proposal updates."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import apply_research_evidence_to_proposals as apply_module
import harvest_model_level_prices as model_harvest
import harvest_price_evidence as price_harvest

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


class PdfExtractionFallbackTests(unittest.TestCase):
    """pdfplumber -> PyMuPDF -> OCR, with explicit failure reporting."""

    def setUp(self):
        self.snapshot = {"snapshot_url": "https://example.invalid/price.pdf"}

    def test_falls_back_to_pymupdf(self):
        failing = Mock(side_effect=RuntimeError("broken pdf"))
        working = Mock(return_value="11.480,? model price")
        meta = {"cache_path": "/tmp/price.pdf", "retrieved_at": "2026-11-21", "error": None}
        chain = (("pdfplumber", failing), ("pymupdf", working), ("ocr", Mock()))
        with patch.object(price_harvest, "fetch_url", return_value=meta), patch.object(
            price_harvest, "EXTRACTORS", chain
        ):
            text, result = price_harvest.extract_text(self.snapshot)
        self.assertEqual(text, "11.480,? model price")
        self.assertEqual(result["extractor"], "pymupdf")
        self.assertIsNone(result["error"])

    def test_falls_back_to_ocr(self):
        fail = Mock(side_effect=RuntimeError("no text layer"))
        ocr = Mock(return_value="scanned price 12.000,?")
        meta = {"cache_path": "/tmp/price.pdf", "retrieved_at": "2026-11-21", "error": None}
        chain = (("pdfplumber", fail), ("pymupdf", fail), ("ocr", ocr))
        with patch.object(price_harvest, "fetch_url", return_value=meta), patch.object(
            price_harvest, "EXTRACTORS", chain
        ):
            text, result = price_harvest.extract_text(self.snapshot)
        self.assertEqual(text, "scanned price 12.000,?")
        self.assertEqual(result["extractor"], "ocr")

    def test_all_extractors_failing_never_fabricates_text(self):
        fail = Mock(side_effect=RuntimeError("broken"))
        meta = {"cache_path": "/tmp/price.pdf", "retrieved_at": "2026-11-21", "error": None}
        chain = (("pdfplumber", fail), ("pymupdf", fail), ("ocr", fail))
        with patch.object(price_harvest, "fetch_url", return_value=meta), patch.object(
            price_harvest, "EXTRACTORS", chain
        ):
            text, result = price_harvest.extract_text(self.snapshot)
        self.assertEqual(text, "")
        self.assertIn("all_extractors_failed", result["error"])
        for name in ("pdfplumber", "pymupdf", "ocr"):
            self.assertIn(name, result["error"])

    def test_german_edition_month_is_parsed(self):
        iso, precision = model_harvest.validity_date(
            "Ausgabe: \u00d6sterreich, M\u00e4rz 2019", "2019-07-18"
        )
        self.assertEqual(iso, "2019-03-01")
        self.assertEqual(precision, "month")

    def test_fabia_rows_are_harvested_from_streuer_with_month_date(self):
        rows = [entry for entry in json.loads(PRICE.read_text(encoding="utf-8"))["entries"]
                if entry["price"]["match"]["matched_model"] == "fabia"]
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(row["purchase_price_incl_vat_eur"], 11480.0)
            self.assertEqual(row["price_date"], "2019-03-01")
            self.assertEqual(row["price_date_precision"], "month")
            self.assertEqual(row["price_precision"], "model_level")
            self.assertFalse(row["tco_ready"])
            self.assertTrue(row["catalog_eligible"])
            self.assertIn("FABIA20", row["source_url"])


if __name__ == "__main__":
    unittest.main()
