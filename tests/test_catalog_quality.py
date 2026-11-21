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

from scripts import catalog_quality as quality
from scripts.catalog_quality import (
    assert_safe_report_path,
    build_report,
    confidence_tier,
    main,
    normalize_identity,
    preflight_input_sizes,
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
        self.assertEqual(first["canonical_key"], "tesla|model-3|highland|rwd-60|2026")

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


class CatalogQualityRegressionTests(unittest.TestCase):
    """One regression per actionable CodeRabbit finding on PR #140."""

    def setUp(self):
        self.tmp = ROOT / "tests" / "fixtures" / "_catalog_quality_regression_tmp"
        if self.tmp.exists():
            shutil.rmtree(self.tmp)
        self.tmp.mkdir()
        self.clean = clean_record()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def report(self, records, now=NOW):
        catalog = make_catalog(self.tmp, records)
        return build_report(catalog, SCHEMA, __import__("datetime").datetime.fromisoformat(now))

    def test_finding_1_report_digest_tracks_evaluation_dependent_age(self):
        first = self.report([self.clean], "2026-11-20T12:00:00Z")
        second = self.report([self.clean], "2026-11-21T12:00:00Z")
        self.assertEqual(first["catalog_sha256"], second["catalog_sha256"])
        self.assertNotEqual(first["report_sha256"], second["report_sha256"])

    def test_finding_2_variant_slug_keeps_distinct_variants(self):
        left = copy.deepcopy(self.clean)
        right = copy.deepcopy(self.clean)
        right["variant_id"] = "tesla.model-3.highland.rwd-75"
        right["identity"]["variant_slug"] = "rwd-75"
        left_identity = normalize_identity(left, left["variant_id"])
        right_identity = normalize_identity(right, right["variant_id"])
        self.assertNotEqual(left_identity["canonical_key"], right_identity["canonical_key"])
        report = self.report([left, right])
        categories = {item["category"] for item in report["findings"]}
        self.assertNotIn("DUPLICATE_IDENTITY", categories)

    def test_finding_3_tier_stays_attached_to_evidence_reference(self):
        record = copy.deepcopy(self.clean)
        record["provenance"]["sources"] = [
            {"name": "official without reference", "confidence": "official"},
            {"name": "low with reference", "url": "https://example.invalid/low",
             "retrieved": "2026-11-20", "confidence": "low"},
        ]
        scored = confidence_tier(record)
        self.assertEqual(scored["tier"], "low")
        self.assertEqual(scored["independent_sources"], 1)
        report = self.report([record])
        self.assertEqual(report["confidence_counts"]["official"], 0)
        self.assertIn("low provenance confidence", " ".join(
            reason for row in report["refresh_plan"] for reason in row["reasons"]
        ))

    def test_finding_4_sparse_offers_are_not_complete(self):
        record = copy.deepcopy(self.clean)
        record["offers"] = [{}]
        report = self.report([record])
        cov = report["variants"][record["variant_id"]]["coverage"]
        self.assertEqual(cov["offers_complete"], 0)
        self.assertLess(cov["completeness_ratio"], 1.0)
        self.assertTrue(any(field.startswith("offers.") for field in cov["critical_missing_fields"]))
        self.assertEqual(report["refresh_plan"][0]["priority"], "P1")

    def test_finding_5_sparse_identity_is_not_a_confirmed_duplicate(self):
        first = copy.deepcopy(self.clean)
        second = copy.deepcopy(self.clean)
        for record, variant_id in ((first, "sparse.one"), (second, "sparse.two")):
            record["variant_id"] = variant_id
            record["identity"] = {"make": "Tesla", "model": "Model 3"}
        report = self.report([first, second])
        categories = {item["category"] for item in report["findings"]}
        self.assertNotIn("DUPLICATE_IDENTITY", categories)

        duplicate = copy.deepcopy(first)
        duplicate["variant_id"] = "sparse.one"
        duplicate_report = self.report([first, duplicate])
        duplicate_categories = {item["category"] for item in duplicate_report["findings"]}
        self.assertIn("DUPLICATE_VARIANT_ID", duplicate_categories)

    def test_finding_6_oversized_input_rejected_before_validation(self):
        catalog = make_catalog(self.tmp, [self.clean])
        large = catalog / "huge.json"
        large.write_bytes(b"x" * 4096)
        with patch.object(quality, "MAX_INPUT_BYTES", 64), patch.object(
            quality, "validate_catalog", side_effect=AssertionError("validator called too early")
        ):
            with self.assertRaisesRegex(quality.QualityError, "exceeds"):
                preflight_input_sizes(catalog)
            with self.assertRaisesRegex(quality.QualityError, "exceeds"):
                build_report(catalog, SCHEMA)

    def test_finding_7_duplicate_ids_contribute_each_measurement(self):
        first = copy.deepcopy(self.clean)
        second = copy.deepcopy(self.clean)
        second["performance"]["power_w"] = None
        report = self.report([first, second])
        self.assertEqual(report["variant_count"], 2)
        self.assertEqual(report["completeness"]["measured_records"], 2)
        self.assertEqual(report["completeness"]["complete_variants"], 1)
        self.assertEqual(
            report["completeness"]["required_fields"],
            2 * report["variants"][first["variant_id"]]["coverage"]["required_fields"],
        )

    def test_finding_8_report_path_cannot_overlap_catalog(self):
        catalog = make_catalog(self.tmp / "catalog", [self.clean])
        record = min(catalog.glob("*.json"))
        before = record.read_bytes()
        self.assertEqual(main([
            "--catalog-dir", str(catalog), "--report", str(record), "--now", NOW,
        ]), 2)
        self.assertEqual(record.read_bytes(), before)

        alias = self.tmp / "alias"
        try:
            alias.symlink_to(catalog, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks are unavailable on this host")
        with self.assertRaises(quality.QualityError):
            assert_safe_report_path(alias / "variant-0.json", catalog)

        safe = self.tmp / "out" / "report.json"
        self.assertEqual(assert_safe_report_path(safe, catalog), safe.resolve())


if __name__ == "__main__":
    unittest.main()
