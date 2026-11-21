"""Offline tests for public-source harvesting and harvest audit logic."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harvest_common as common
import harvest_identity_evidence as identity_harvest
import harvest_price_evidence as price_harvest
from audit_harvest_quality import build_report
from report_research_coverage import analyze_sample

IDENTITY = ROOT / "docs" / "data-sources" / "identity-map" / "v1.json"
PRICE = ROOT / "docs" / "data-sources" / "price-evidence" / "v1.json"
SAMPLE = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2018_wltp_sample.tsv"
KEY_FIELDS = ("make", "model", "variant", "powertrain", "model_year", "market")
PROVENANCE = ("source_url", "license", "retrieved_at", "confidence", "reviewed_by")


class HarvestEvidenceTests(unittest.TestCase):
    def test_identity_evidence_schema_and_provenance(self):
        data = json.loads(IDENTITY.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(len({e["variant"] for e in data["entries"]}), 57)
        for entry in data["entries"]:
            for field in (*KEY_FIELDS, "consumer_make", "consumer_model", *PROVENANCE):
                self.assertTrue(str(entry.get(field) or "").strip(), f"{entry['variant']}: {field}")
            self.assertNotEqual(entry["consumer_make"].casefold(), entry["consumer_model"].casefold())
            self.assertTrue(entry["source_url"].startswith("https://"))
            self.assertEqual(entry["market"], "AT")
            self.assertEqual(entry["model_year"], 2018)
            self.assertTrue(any(check.get("matched") for check in entry["cross_checks"]))

    def test_price_evidence_is_owner_approved_model_level_and_unresolved_is_explicit(self):
        data = json.loads(PRICE.read_text(encoding="utf-8"))
        unresolved = json.loads(PRICE.with_name("unresolved.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["entries"]), 31)
        for row in data["entries"]:
            self.assertEqual(row["price_precision"], "model_level")
            self.assertEqual(row["confidence"], "low")
            self.assertFalse(row["tco_ready"])
            self.assertTrue(row["catalog_eligible"])
            self.assertFalse(row["price_pending"])
        self.assertEqual(unresolved["count"], 27)
        for row in unresolved["variants"]:
            self.assertEqual(row["reason"], "no_model_level_price_source")
            self.assertTrue(row["detail"])

    def test_no_fabrication_when_identity_source_is_blank(self):
        variants = [{
            "make": "NISSAN", "model": "NISSAN", "variant": "A02",
            "powertrain": "bev", "model_year": 2018, "market": "AT",
            "commercial_name": "", "eea_record_ids": ["2887803"],
            "type_approval_numbers": [],
        }]
        with patch.object(identity_harvest, "sitemap_check") as check:
            document, unresolved, _ = identity_harvest.build_evidence(variants, 2018)
        self.assertEqual(document["entries"], [])
        self.assertEqual(unresolved["count"], 1)
        self.assertEqual(unresolved["variants"][0]["reason"], "no_source_found")
        check.assert_not_called()

    def test_sitemap_failure_leaves_variant_unresolved(self):
        variants = [{
            "make": "NISSAN", "model": "NISSAN", "variant": "A02",
            "powertrain": "bev", "model_year": 2018, "market": "AT",
            "commercial_name": "NISSAN LEAF 40KWH",
            "eea_record_ids": ["2887803"], "type_approval_numbers": [],
        }]
        blocked = {"source": "https://example.invalid/sitemap.xml", "matched": False,
                   "error": "robots_disallowed"}
        with patch.object(identity_harvest, "sitemap_check", return_value=blocked):
            document, unresolved, _ = identity_harvest.build_evidence(variants, 2018)
        self.assertEqual(document["entries"], [])
        self.assertEqual(unresolved["variants"][0]["reason"], "tos_blocked")

    def test_robots_disallow_is_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            common._ROBOTS.clear()
            common.CACHE_DIR = Path(directory) / "cache"
            payload = b"User-agent: *\nDisallow: /\n"
            with patch.object(common.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
                allowed = common.robots_allows("https://example.invalid/some/page")
            self.assertFalse(allowed)
            common._ROBOTS.clear()

    def test_robots_404_means_no_restriction(self):
        common._ROBOTS.clear()
        error = common.urllib.error.HTTPError("https://example.invalid/robots.txt", 404, "not found", {}, None)
        with patch.object(common.urllib.request, "urlopen", side_effect=error):
            allowed = common.robots_allows("https://example.invalid/some/page")
        self.assertTrue(allowed)
        common._ROBOTS.clear()

    def test_rate_limiter_sleeps_only_when_needed(self):
        times = iter([100.0, 100.5, 200.0])
        common._LAST_REQUEST.clear()
        with patch.object(common.time, "monotonic", side_effect=lambda: next(times)), patch.object(
            common.time, "sleep"
        ) as sleep:
            common._throttle("example.invalid")
            common._throttle("example.invalid")
        sleep.assert_called_once()
        common._LAST_REQUEST.clear()

    def test_price_parsing_and_validation(self):
        self.assertEqual(price_harvest.parse_price("24.990,50"), 24990.5)
        self.assertEqual(price_harvest.parse_price("35.000"), 35000.0)
        for invalid in ("0", "-5", "abc", None, ""):
            self.assertIsNone(price_harvest.parse_price(invalid))
        row = {
            "purchase_price_excl_vat_eur": 35000.0, "price_date": "2018-01-01",
            "currency": "EUR", "market": "AT", "source_url": "https://example.invalid",
            "license": "OEM", "retrieved_at": "2026-11-21",
        }
        self.assertEqual(price_harvest.validate_price_row(row), [])
        for field, value in (("purchase_price_excl_vat_eur", 0), ("price_date", ""),
                             ("source_url", ""), ("currency", "USD")):
            bad = dict(row, **{field: value})
            self.assertTrue(price_harvest.validate_price_row(bad))

    def test_audit_flags_missing_price_but_passes_two_source_identity(self):
        report = build_report(SAMPLE, IDENTITY, PRICE)
        self.assertEqual(report["checked_variants"], 58)
        self.assertEqual(report["identity_pass_count"], 58)
        self.assertEqual(report["price_pass_count"], 31)
        self.assertEqual(report["catalog_eligible_count"], 31)
        self.assertEqual(report["tco_ready_count"], 0)
        self.assertEqual(report["single_source_identity_count"], 0)
        first = report["variants"][0]
        self.assertEqual(first["identity"]["sources"], 2)
        self.assertTrue(first["catalog_eligible"])
        self.assertFalse(first["tco_ready"])

    def test_coverage_report_reads_harvested_evidence_without_catalog_writes(self):
        catalog = ROOT / "catalog" / "variants"
        before = {path.name: path.read_bytes() for path in catalog.glob("*.json")}
        report = analyze_sample(
            sample=SAMPLE,
            identity_map=IDENTITY,
            price_evidence=PRICE,
        )
        self.assertEqual(report["identity"]["resolvable"], 154)
        self.assertEqual(report["identity"]["resolvable_pct"], 100.0)
        self.assertEqual(report["price"]["verified"], 95)
        self.assertEqual(report["price"]["precision_breakdown"]["model_level"], 95)
        self.assertEqual(report["gate_ready_after_resolution"]["count"], 95)
        self.assertEqual(report["gate_ready_after_resolution"]["tco_ready_count"], 0)
        self.assertEqual(report["catalog_variants_written"], 0)
        self.assertEqual({path.name: path.read_bytes() for path in catalog.glob("*.json")}, before)


if __name__ == "__main__":
    unittest.main()
