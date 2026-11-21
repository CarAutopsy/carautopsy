"""Offline regression tests for catalog normalization, quality and refresh planning."""
from __future__ import annotations

import copy
import json
import shutil
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.catalog_quality import (
    build_report,
    confidence_tier,
    main,
    normalize_identity,
    report_digest,
    slugify,
)

NOW = "2026-11-25T12:00:00Z"
CLEAN = ROOT / "tests" / "fixtures" / "catalog_quality" / "clean.json"
SCHEMA = ROOT / "schemas" / "vehicle-variant.schema.json"


def clean_record() -> dict:
    return json.loads(CLEAN.read_text(encoding="utf-8"))


def make_catalog(root: Path, records: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for index, record in enumerate(records):
        (root / f"variant-{index}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
    return root


class CatalogQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = ROOT / "tests" / "fixtures" / "_catalog_quality_tmp"
        if self.tmp.exists():
            shutil.rmtree(self.tmp)
        self.tmp.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def report(self, records, now=NOW):
        catalog = make_catalog(self.tmp, records)
        return build_report(catalog, SCHEMA, __import__("datetime").datetime.fromisoformat(now))

    def test_clean_fixture_is_complete_and_current(self):
        report = self.report([clean_record()])

        self.assertEqual(report["variant_count"], 1)
        self.assertEqual(report["structural_error_count"], 0)
        self.assertEqual(report["blocking_finding_count"], 0)
        self.assertEqual(report["completeness"]["ratio"], 1.0)
        self.assertEqual(report["completeness"]["complete_variants"], 1)
        self.assertEqual(report["confidence_counts"]["official"], 1)
        self.assertEqual(report["refresh_plan"][0]["priority"], "P2")
        self.assertFalse(report["refresh_plan"][0]["refresh_enabled"])
        self.assertFalse(report["refresh_plan"][0]["network_permitted"])

    def test_slugify_is_deterministic_and_safe(self):
        self.assertEqual(slugify("Model 3"), "model-3")
        self.assertEqual(slugify("  Hochland / RWD "), "hochland-rwd")
        self.assertIsNone(slugify(None))
        self.assertIsNone(slugify("   "))

    def test_identity_normalization_groups_generation_and_year(self):
        record = clean_record()
        first = normalize_identity(record, record["variant_id"])
        second = normalize_identity(copy.deepcopy(record), record["variant_id"])

        self.assertEqual(first, second)
        self.assertEqual(first["make_slug"], "tesla")
        self.assertEqual(first["model_slug"], "model-3")
        self.assertEqual(first["generation_slug"], "highland")
        self.assertEqual(first["canonical_key"], "tesla|model-3|highland|rwd|2026")

    def test_confidence_scoring_uses_independent_evidence(self):
        record = clean_record()
        self.assertEqual(confidence_tier(record)["tier"], "official")
        record["provenance"]["sources"] = [
            {"name": "a", "url": "https://example.invalid/a", "retrieved": "2026-11-20", "confidence": "medium"},
            {"name": "b", "url": "https://example.invalid/b", "retrieved": "2026-11-20", "confidence": "medium"},
        ]
        self.assertEqual(confidence_tier(record)["tier"], "high")
        record["provenance"]["sources"] = [
            {"name": "a", "url": "https://example.invalid/a", "retrieved": "2026-11-20", "confidence": "low"}
        ]
        self.assertEqual(confidence_tier(record)["tier"], "low")
        record["provenance"]["sources"] = []
        self.assertEqual(confidence_tier(record)["tier"], "unknown")

    def test_missing_critical_fields_lower_completeness_and_raise_priority(self):
        record = clean_record()
        record["performance"]["power_w"] = None
        record["energy"]["battery_usable_wh"] = None
        report = self.report([record])

        self.assertLess(report["completeness"]["ratio"], 1.0)
        categories = {item["category"] for item in report["findings"]}
        self.assertIn("MISSING_CRITICAL_FIELD", categories)
        self.assertEqual(report["refresh_plan"][0]["priority"], "P1")

    def test_duplicate_variant_id_is_blocking(self):
        first = clean_record()
        second = clean_record()
        second["performance"]["power_w"] = 999000
        report = self.report([first, second])

        categories = {item["category"] for item in report["findings"]}
        self.assertIn("DUPLICATE_VARIANT_ID", categories)
        self.assertGreater(report["blocking_finding_count"], 0)

    def test_conflicting_specification_is_detected(self):
        first = clean_record()
        second = clean_record()
        second["variant_id"] = "tesla.model-3.highland.rwd-60-alt"
        second["performance"]["power_w"] = 390000
        report = self.report([first, second])

        categories = {item["category"] for item in report["findings"]}
        self.assertIn("DUPLICATE_IDENTITY", categories)
        self.assertIn("CONFLICTING_SPECIFICATION", categories)
        self.assertGreater(report["blocking_finding_count"], 0)

    def test_stale_source_is_reported(self):
        record = clean_record()
        record["provenance"]["sources"][0]["retrieved"] = "2025-01-01"
        report = self.report([record])

        categories = {item["category"] for item in report["findings"]}
        self.assertIn("STALE_SOURCE", categories)
        self.assertEqual(report["refresh_plan"][0]["priority"], "P1")

    def test_structural_validation_errors_are_preserved(self):
        record = clean_record()
        del record["identity"]["make"]
        report = self.report([record])

        self.assertGreater(report["structural_error_count"], 0)
        categories = {item["category"] for item in report["findings"]}
        self.assertIn("STRUCTURAL_ERROR", categories)

    def test_report_digest_excludes_generated_at(self):
        report = self.report([clean_record()])
        changed = copy.deepcopy(report)
        changed["generated_at"] = "1999-01-01T00:00:00Z"

        self.assertEqual(report["report_sha256"], report_digest(report))
        self.assertEqual(report["report_sha256"], report_digest(changed))

    def test_gates_remain_paused(self):
        report = self.report([clean_record()])

        self.assertTrue(report["gates"]["HIVE_RESEARCH_PAUSED"])
        self.assertFalse(report["gates"]["VERIFIED_RETRIEVAL_AVAILABLE"])
        self.assertFalse(report["refresh_execution_enabled"])
        source = (ROOT / "scripts" / "autonomous_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("VERIFIED_RETRIEVAL_AVAILABLE = False", source)

    def test_no_network_or_provider_calls(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("network or provider call attempted")

        with patch.object(socket, "socket", forbidden), patch("requests.post", forbidden):
            report = self.report([clean_record()])

        self.assertEqual(report["network_calls"], 0)
        self.assertEqual(report["provider_calls"], 0)

    def test_cli_writes_report_and_returns_exit_codes(self):
        report_path = self.tmp / "report.json"
        catalog = make_catalog(self.tmp / "clean", [clean_record()])
        self.assertEqual(main([
            "--catalog-dir", str(catalog), "--report", str(report_path), "--now", NOW,
        ]), 0)
        self.assertTrue(report_path.is_file())

        conflict = clean_record()
        duplicate = clean_record()
        duplicate["performance"]["power_w"] = 999000
        conflict_dir = make_catalog(self.tmp / "conflict", [conflict, duplicate])
        self.assertEqual(main([
            "--catalog-dir", str(conflict_dir), "--report", str(self.tmp / "conflict.json"), "--now", NOW,
        ]), 1)

        bad = clean_record()
        bad["identity"]["make"] = 12345
        bad_dir = make_catalog(self.tmp / "bad", [bad])
        self.assertEqual(main([
            "--catalog-dir", str(bad_dir), "--report", str(self.tmp / "bad.json"), "--now", NOW,
        ]), 1)

        malformed = self.tmp / "malformed.json"
        malformed.write_text("{not json}", encoding="utf-8")
        self.assertEqual(main([
            "--catalog-dir", str(malformed.parent), "--report", str(self.tmp / "malformed-report.json"), "--now", NOW,
        ]), 2)


if __name__ == "__main__":
    unittest.main()
