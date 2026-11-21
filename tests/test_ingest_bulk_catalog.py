"""Offline tests for bulk catalog ingestion (no network, no catalog writes)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import ingest_bulk_catalog as ingest

SAMPLE = ROOT / "docs" / "data-sources" / "sample" / "eea_at_2018_wltp_sample.tsv"
IDENTITY = ROOT / "docs" / "data-sources" / "identity-map" / "v1.json"
PRICE = ROOT / "docs" / "data-sources" / "price-evidence" / "v1.json"
RULES = ROOT / "docs" / "data-sources" / "statutory" / "at-rules-v1.json"
SELECTION = ROOT / "docs" / "data-sources" / "bulk-source-selection.md"
CONFIG = ROOT / "docs" / "data-sources" / "bulk-sources" / "eea-at-2018.json"


def sample_lines(count: int, id_offset: int = 9000000) -> list[str]:
    lines = SAMPLE.read_text(encoding="utf-8").splitlines()
    header = lines[0]
    selected = lines[1:1 + count]
    out = [header]
    for index, line in enumerate(selected):
        parts = line.split("\t")
        parts[0] = str(id_offset + index)
        out.append("\t".join(parts))
    return out


class IngestBulkCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for directory in (
            "docs/data-sources/bulk-sources", "docs/data-sources/sample",
            "docs/data-sources/identity-map", "docs/data-sources/price-evidence",
            "docs/data-sources/statutory", "catalog/variants",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "docs/data-sources/bulk-source-selection.md").write_text(
            SELECTION.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (self.root / "docs/data-sources/sample/eea.tsv").write_text(
            "\n".join(sample_lines(6)) + "\n", encoding="utf-8"
        )
        for source, target in (
            (IDENTITY, "docs/data-sources/identity-map/v1.json"),
            (PRICE, "docs/data-sources/price-evidence/v1.json"),
            (RULES, "docs/data-sources/statutory/at-rules-v1.json"),
            (CONFIG, "docs/data-sources/bulk-sources/eea-at-2018.json"),
        ):
            (self.root / target).write_bytes(source.read_bytes())
        self.config = self.root / "docs/data-sources/bulk-sources/eea-at-2018.json"
        config_data = json.loads(self.config.read_text(encoding="utf-8"))
        config_data["sample"] = "docs/data-sources/sample/eea.tsv"
        self.config.write_text(json.dumps(config_data), encoding="utf-8")
        self.report = self.root / "report.json"
        self.live_catalog = ROOT / "catalog" / "variants"

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def patched(self):
        with patch.object(ingest, "ROOT", self.root), patch.object(
            ingest, "CATALOG_DIR", self.root / "catalog" / "variants"
        ), patch.object(ingest, "STAGING_ROOT", self.root / "staging"):
            yield

    def catalog_bytes(self) -> dict[str, bytes]:
        return {path.name: path.read_bytes() for path in self.live_catalog.glob("*.json")}

    def invoke(self, *extra: str) -> int:
        with self.patched():
            return ingest.main([
                "--source", str(self.config), "--report", str(self.report), *extra,
            ])

    def load_report(self) -> dict:
        return json.loads(self.report.read_text(encoding="utf-8"))

    def test_source_gate_fails_when_selection_doc_missing(self):
        (self.root / "docs/data-sources/bulk-source-selection.md").unlink()
        with self.patched(), self.assertRaises(ingest.IngestError) as caught:
            ingest.load_source_config(self.config, self.root)
        self.assertEqual(caught.exception.code, ingest.EXIT_GATE)

    def test_source_gate_fails_when_doc_does_not_name_permitted_source(self):
        path = self.root / "docs/data-sources/bulk-source-selection.md"
        path.write_text("no permitted source documented", encoding="utf-8")
        with self.patched(), self.assertRaises(ingest.IngestError) as caught:
            ingest.load_source_config(self.config, self.root)
        self.assertEqual(caught.exception.code, ingest.EXIT_GATE)

    def test_config_missing_field_returns_usage_exit(self):
        data = json.loads(self.config.read_text(encoding="utf-8"))
        del data["license"]
        self.config.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.invoke("--dry-run"), ingest.EXIT_USAGE)

    def test_dry_run_reports_counts_and_writes_no_files(self):
        before = self.catalog_bytes()
        self.assertEqual(self.invoke("--dry-run", "--limit", "6"), ingest.EXIT_OK)
        report = self.load_report()
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["counts"]["read"], 6)
        self.assertEqual(report["counts"]["written"], 0)
        self.assertEqual(report["catalog_variants_written"], 0)
        self.assertFalse((self.root / "staging").exists())
        self.assertEqual(self.catalog_bytes(), before)

    def test_missing_evidence_rows_are_rejected_with_reasons(self):
        path = self.root / "docs/data-sources/sample/eea.tsv"
        lines = path.read_text(encoding="utf-8").splitlines()
        parts = lines[1].split("\t")
        parts[10] = "UNRESOLVED-CODE"  # Ve field
        lines[1] = "\t".join(parts)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(self.invoke("--dry-run", "--limit", "6"), ingest.EXIT_OK)
        report = self.load_report()
        rejected = {item["variant_id"]: item["reasons"] for item in report["rejections"]}
        reasons = [reason for value in rejected.values() for reason in value]
        self.assertIn("identity_evidence_missing", reasons)
        self.assertIn("price_evidence_missing", reasons)

    def test_invalid_price_is_rejected(self):
        path = self.root / "docs/data-sources/price-evidence/v1.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data["entries"]:
            entry["purchase_price_excl_vat_eur"] = 0
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.invoke("--dry-run", "--limit", "6"), ingest.EXIT_OK)
        report = self.load_report()
        all_reasons = [reason for item in report["rejections"] for reason in item["reasons"]]
        self.assertIn("price_evidence_incomplete", all_reasons)

    def test_batch_mode_writes_only_to_staging(self):
        before = self.catalog_bytes()
        with patch.object(ingest, "existing_catalog_records", return_value=[]):
            code = self.invoke("--limit", "6", "--batch-size", "3",
                               "--output-dir", "staging/catalog-batch-001")
        self.assertEqual(code, ingest.EXIT_OK)
        report = self.load_report()
        self.assertGreater(report["counts"]["written"], 0)
        self.assertLessEqual(report["counts"]["written"], 3)
        staged = sorted((self.root / "staging/catalog-batch-001").glob("*.json"))
        self.assertEqual(len(staged), report["counts"]["written"])
        for path in staged:
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(record["catalog_written"])
            self.assertEqual(record["ingestion"]["source_url"], record["ingestion"]["source_url"])
            self.assertIn("source_url", record["ingestion"])
            self.assertIn("license", record["ingestion"])
            self.assertIn("extraction_date", record["ingestion"])
            self.assertIn("source_url", record["resolved_identity"])
            self.assertIn("source_url", record["price_verification"])
            self.assertFalse(record["tco_ready"])
            self.assertTrue(record["catalog_eligible"])
        self.assertEqual(self.catalog_bytes(), before)

    def test_duplicate_groups_keep_first_record(self):
        path = self.root / "docs/data-sources/sample/eea.tsv"
        lines = path.read_text(encoding="utf-8").splitlines()
        duplicate = lines[1].split("\t")
        duplicate[0] = "9099999"
        lines.append("\t".join(duplicate))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with patch.object(ingest, "existing_catalog_records", return_value=[]):
            self.assertEqual(
                self.invoke("--dry-run", "--limit", "7"), ingest.EXIT_OK
            )
        report = self.load_report()
        self.assertGreaterEqual(report["counts"]["duplicates"], 1)

    def test_conflict_finding_excludes_record(self):
        conflict = {"category": "CONFLICTING_SPECIFICATION", "record_id": "x",
                    "message": "conflict", "severity": "ERROR"}
        with patch.object(ingest, "existing_catalog_records", return_value=[]), patch.object(
            ingest, "detect_duplicates", return_value=[conflict]
        ):
            self.assertEqual(self.invoke("--dry-run", "--limit", "6"), ingest.EXIT_OK)
        report = self.load_report()
        self.assertEqual(report["counts"]["conflicts"], 1)

    def test_schema_invalid_record_is_rejected(self):
        error = Mock()
        error.message = "bad schema"
        validator = Mock()
        validator.iter_errors.return_value = [error]
        with patch.object(ingest, "Draft7Validator", return_value=validator):
            self.assertEqual(self.invoke("--dry-run", "--limit", "6"), ingest.EXIT_OK)
        all_reasons = [reason for item in self.load_report()["rejections"] for reason in item["reasons"]]
        self.assertIn("schema_invalid", all_reasons)

    def test_unsafe_output_paths_are_rejected(self):
        with self.patched():
            with self.assertRaises(ingest.IngestError) as caught:
                ingest.safe_output_dir(self.root / "catalog/variants", self.root)
            self.assertEqual(caught.exception.code, ingest.EXIT_UNSAFE_PATH)
            with self.assertRaises(ingest.IngestError):
                ingest.safe_output_dir(self.root / "reports", self.root)
            with self.assertRaises(ingest.IngestError):
                ingest.safe_report_path(self.root / "catalog/variants/x.json", self.root)
        self.assertEqual(
            self.invoke("--limit", "6", "--output-dir", "catalog/variants"),
            ingest.EXIT_UNSAFE_PATH,
        )

    def test_output_dir_required_without_dry_run(self):
        self.assertEqual(self.invoke("--limit", "6"), ingest.EXIT_USAGE)

    def test_dry_run_caps_at_200_records(self):
        path = self.root / "docs/data-sources/sample/eea.tsv"
        lines = sample_lines(6, id_offset=8000000)
        header, body = lines[0], lines[1:]
        path.write_text("\n".join([header] + body * 45) + "\n", encoding="utf-8")
        self.assertEqual(self.invoke("--dry-run", "--limit", "500"), ingest.EXIT_OK)
        report = self.load_report()
        self.assertEqual(report["counts"]["read"], ingest.MAX_DRY_RUN_RECORDS)
        self.assertEqual(report["counts"]["written"], 0)


if __name__ == "__main__":
    unittest.main()
