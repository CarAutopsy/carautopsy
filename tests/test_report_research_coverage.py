"""Offline tests for the research-only identity/price coverage report."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from report_research_coverage import (
    DEFAULT_SAMPLE,
    ResearchReportError,
    analyze_sample,
    assert_report_output_safe,
    key_fields,
    load_evidence,
    main,
)
from validate_eea_with_adapters import map_row, read_rows


def bev_record() -> dict:
    rows = read_rows(DEFAULT_SAMPLE)
    row = next(row for row in rows if row["Ft"].strip().upper() == "ELECTRIC")
    return map_row(row, 2018, None)


def valid_identity_row(record: dict) -> dict:
    key = key_fields(record)
    row = dict(key)
    row.update({
        "consumer_make": "Nissan",
        "consumer_model": "Leaf",
        "trim": "Tekna",
        "generation": "ZE1",
        "source_url": "https://example.invalid/identity-evidence",
        "license": "owner-curated",
        "retrieved_at": "2026-11-21",
        "reviewed_by": "owner",
    })
    return row


def valid_price_row(record: dict) -> dict:
    key = key_fields(record)
    row = dict(key)
    row.update({
        "purchase_price_excl_vat_eur": 35000.0,
        "price_date": "2018-01-01",
        "currency": "EUR",
        "market": "AT",
        "source_url": "https://example.invalid/price-evidence",
        "license": "owner-curated",
        "retrieved_at": "2026-11-21",
    })
    return row


def write_evidence(directory: Path, name: str, rows: list[dict]) -> Path:
    path = directory / name
    path.write_text(
        json.dumps({"schema_version": 1, "entries": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


class ResearchCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.record = bev_record()

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, identity_rows=None, price_rows=None):
        identity_map = None
        price_evidence = None
        if identity_rows is not None:
            identity_map = write_evidence(self.dir, "identity.json", identity_rows)
        if price_rows is not None:
            price_evidence = write_evidence(self.dir, "price.json", price_rows)
        return analyze_sample(
            sample=DEFAULT_SAMPLE,
            identity_map=identity_map,
            price_evidence=price_evidence,
        )

    def test_missing_evidence_reports_zero_and_explicit_reasons(self):
        report = self.report()
        self.assertEqual(report["sampled"], 154)
        self.assertTrue(report["sampled_only"])
        self.assertEqual(report["identity"]["resolvable"], 0)
        self.assertEqual(report["price"]["verified"], 0)
        self.assertEqual(report["gate_ready_after_resolution"]["count"], 0)
        self.assertEqual(
            report["identity"]["reasons"], {"no_identity_evidence_file": 154}
        )
        self.assertEqual(report["price"]["reasons"], {"no_price_evidence_file": 154})
        self.assertFalse(report["price"]["compliant_bulk_source_available"])
        self.assertEqual(report["catalog_variants_written"], 0)
        self.assertEqual(report["baseline"]["distinct_variant_codes"], 57)
        self.assertEqual(report["baseline"]["identity_quality_ok_before_research"], 0)
        self.assertEqual(report["baseline"]["readiness_gate_passing_before_research"], 9)

    def test_valid_evidence_resolves_identity_price_and_full_gate(self):
        report = self.report(
            [valid_identity_row(self.record)], [valid_price_row(self.record)]
        )
        # All 9 Nissan A02 rows share the same exact match key.
        self.assertEqual(report["identity"]["resolvable"], 9)
        self.assertEqual(report["price"]["verified"], 9)
        self.assertEqual(report["gate_ready_after_resolution"]["count"], 9)
        self.assertEqual(report["gate_ready_after_resolution"]["pct"], 5.8)
        self.assertEqual(report["identity"]["resolvable_pct"], 5.8)
        self.assertEqual(report["price"]["verified_pct"], 5.8)

    def test_incomplete_identity_row_is_not_resolved(self):
        row = valid_identity_row(self.record)
        del row["generation"]
        report = self.report([row], [valid_price_row(self.record)])
        self.assertEqual(report["identity"]["resolvable"], 0)
        self.assertEqual(report["gate_ready_after_resolution"]["count"], 0)
        self.assertEqual(
            report["identity"]["reasons"],
            {"incomplete_identity_mapping_row": 9, "no_exact_identity_mapping_row": 145},
        )

    def test_incomplete_price_row_is_not_verified(self):
        row = valid_price_row(self.record)
        row["purchase_price_excl_vat_eur"] = None
        report = self.report([valid_identity_row(self.record)], [row])
        self.assertEqual(report["price"]["verified"], 0)
        self.assertEqual(report["gate_ready_after_resolution"]["count"], 0)
        self.assertEqual(
            report["price"]["reasons"],
            {"incomplete_price_row": 9, "no_exact_price_row": 145},
        )

    def test_non_matching_key_never_resolves(self):
        wrong = valid_identity_row(self.record)
        wrong["model_year"] = 2019
        report = self.report([wrong], [valid_price_row(self.record)])
        self.assertEqual(report["identity"]["resolvable"], 0)
        self.assertEqual(
            report["identity"]["reasons"], {"no_exact_identity_mapping_row": 154}
        )

    def test_load_evidence_rejects_malformed_file(self):
        path = self.dir / "bad.json"
        path.write_text('{"schema_version": 2, "entries": []}', encoding="utf-8")
        with self.assertRaises(ResearchReportError):
            load_evidence(path)

    def test_report_output_cannot_overlap_catalog(self):
        catalog_record = ROOT / "catalog" / "variants" / "tesla.model-3.highland.rwd-60.json"
        self.assertTrue(catalog_record.is_file())
        with self.assertRaises(ResearchReportError):
            assert_report_output_safe(catalog_record)
        with self.assertRaises(ResearchReportError):
            assert_report_output_safe(ROOT / "catalog")
        self.assertEqual(
            assert_report_output_safe(self.dir / "report.json"),
            (self.dir / "report.json").resolve(),
        )

    def test_main_does_not_mutate_proposals_or_catalog(self):
        proposal = ROOT / "docs" / "data-sources" / "proposals" / "nissan.nissan.a02.2018.2887803.json"
        before = proposal.read_bytes()
        catalog = ROOT / "catalog" / "variants"
        catalog_before = {path.name: path.read_bytes() for path in catalog.glob("*.json")}
        output = self.dir / "report.json"
        with patch.object(sys, "argv", [
            "report_research_coverage.py",
            "--identity-map", str(self.dir / "missing-identity.json"),
            "--price-evidence", str(self.dir / "missing-price.json"),
            "--output", str(output),
        ]):
            self.assertEqual(main(), 0)
        self.assertEqual(proposal.read_bytes(), before)
        self.assertEqual(
            {path.name: path.read_bytes() for path in catalog.glob("*.json")},
            catalog_before,
        )
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["sampled"], 154)
        self.assertEqual(data["catalog_variants_written"], 0)


if __name__ == "__main__":
    unittest.main()
