"""Tests for the committed-data coverage scoreboard generator."""
import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import coverage_scoreboard as scoreboard


def rec(model, tier):
    return {"brand": "X", "model": model, "price_tier": tier}


class CoverageTests(unittest.TestCase):
    def test_counts_and_coverage(self):
        candidates = [
            rec("Golf", "approximate"),
            rec("Octavia", "verified"),
            rec("Golf", "unavailable"),
            rec("X1", "unavailable"),
        ]
        report = scoreboard.generate(candidates, {"Golf": 1.0, "Octavia": 2.0, "X1": 3.0})
        self.assertEqual(report["total_models"], 4)
        self.assertEqual(report["models_by_price_tier"]["approximate"], 1)
        self.assertEqual(report["unavailable_count"], 2)
        self.assertEqual(report["correction_queue_count"], 3)
        self.assertEqual(report["tco_ready_count"], 1)
        self.assertAlmostEqual(report["price_quality_coverage"], 0.5)
        self.assertAlmostEqual(report["registration_weighted_coverage"], 3 / 7, places=5)
        self.assertEqual(report["coverage_gaps"], ["Golf", "X1"])

    def test_no_weights_yields_null_weighted_coverage(self):
        report = scoreboard.generate([rec("Golf", "approximate")], {})
        self.assertIsNone(report["registration_weighted_coverage"])

    def test_committed_weights_are_marked_provisional(self):
        report = scoreboard.generate_from_files(
            ROOT / "docs/research/pilot-gap-price-candidates.json"
        )
        self.assertEqual(report["weights_status"], "provisional_priority_proxy")
        self.assertEqual(report["total_models"], 48)
        self.assertEqual(report["approximate_count"], 12)
        self.assertEqual(report["unavailable_count"], 36)
        self.assertEqual(len(report["coverage_gaps"]), 36)

    def test_generate_from_files_writes_report_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.json"
            weights = root / "weights.json"
            report_path = root / "report.json"
            candidates.write_text(json.dumps([rec("Golf", "approximate")]), encoding="utf-8")
            weights.write_text(json.dumps({"status": "provisional_priority_proxy",
                                           "weights": {"Golf": 1.0}}), encoding="utf-8")
            scoreboard.main(["--candidates", str(candidates), "--weights", str(weights),
                             "--report", str(report_path)])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["registration_weighted_coverage"], 1.0)
            self.assertEqual(report["total_models"], 1)
            self.assertEqual(list((root / "catalog").glob("*")), [])


if __name__ == "__main__":
    unittest.main()
