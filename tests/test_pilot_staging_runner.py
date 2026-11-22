"""Tests for the branch-scoped pilot staging runner."""
import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pilot_staging_runner as runner


def candidate(model="Golf", **overrides):
    record = {
        "brand": "Volkswagen", "model": model, "variant": "Trend", "model_year": 2026,
        "price_tier": "approximate", "price_value": 26790.0, "currency": "EUR",
        "vat_basis": "incl_vat", "price_source_url": "https://www.volkswagen.at/golf/golf",
        "price_source_date": "2026-11-22", "price_confidence": "medium",
        "review_required": True,
    }
    record.update(overrides)
    return record


class StagingRunnerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "staging").mkdir()
        (self.root / "catalog" / "variants").mkdir(parents=True)
        self.candidates = self.root / "candidates.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, records):
        self.candidates.write_text(json.dumps(records), encoding="utf-8")

    def test_dry_run_writes_no_staging_files(self):
        self.write([candidate()])
        report = runner.run(self.candidates, output_dir=self.root / "staging/batch-001",
                            dry_run=True, root=self.root)
        self.assertEqual(report["status"], "DRY_RUN")
        self.assertEqual(report["accepted"], 1)
        self.assertEqual(report["written"], 0)
        self.assertFalse((self.root / "staging/batch-001").exists())

    def test_valid_batch_writes_only_to_branch_scoped_staging(self):
        self.write([candidate()])
        target = self.root / "staging/batch-001"
        report = runner.run(self.candidates, output_dir=target, root=self.root)
        self.assertEqual(report["status"], "STAGED")
        self.assertEqual(report["written"], 1)
        files = list(target.glob("*.json"))
        self.assertEqual(len(files), 1)
        record = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertFalse(record["catalog_written"])
        self.assertTrue(record["staging_only"])
        self.assertEqual(record["price_value"], 26790.0)
        self.assertEqual(record["vat_basis"], "incl_vat")
        self.assertTrue(record["review_required"])
        self.assertEqual(list((self.root / "catalog/variants").glob("*.json")), [])

    def test_invalid_candidate_blocks_entire_batch(self):
        self.write([candidate(), candidate("Golf", price_value=0)])
        target = self.root / "staging/batch-002"
        report = runner.run(self.candidates, output_dir=target, root=self.root)
        self.assertEqual(report["status"], "REJECTED")
        self.assertEqual(report["written"], 0)
        self.assertFalse(target.exists())

    def test_duplicate_and_conflict_counts(self):
        self.write([candidate(), candidate(), candidate(price_value=99999)])
        report = runner.run(self.candidates, dry_run=True, root=self.root)
        self.assertEqual(report["duplicates"], 1)
        self.assertEqual(report["conflicts"], 1)
        self.assertEqual(report["accepted"], 1)

    def test_unsafe_output_path_is_refused(self):
        self.write([candidate()])
        with self.assertRaises(runner.StagingError) as ctx:
            runner.run(self.candidates, output_dir=self.root / "catalog/variants", root=self.root)
        self.assertEqual(ctx.exception.code, "UNSAFE_OUTPUT_PATH")

    def test_report_records_zero_catalog_writes(self):
        self.write([candidate()])
        report = runner.run(self.candidates, dry_run=True, root=self.root)
        self.assertEqual(report["catalog_variants_written"], 0)
        self.assertEqual(report["provider_calls"], 0)


if __name__ == "__main__":
    unittest.main()
