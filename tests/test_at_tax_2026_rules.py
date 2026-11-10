"""Regression targets for the Austrian 2026 tax migration.

These tests validate the staged BMF rule data, not the legacy TCO engine.
The draft PR is NOT merge-ready until the engine consumes these rules.
"""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = yaml.safe_load((ROOT / "country-packs/AT/taxes.yaml").read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((ROOT / "country-packs/AT/manifest.yaml").read_text(encoding="utf-8"))

class Austrian2026RuleTests(unittest.TestCase):
    def test_not_marked_verified(self):
        self.assertEqual(RULES["status"], "draft")
        self.assertEqual(MANIFEST["status"], "draft")

    def test_nova_2026_parameters(self):
        f = RULES["nova"]["formula"]
        self.assertEqual((f["co2_deduction_gkm"], f["divisor"], f["max_percentage"]), (91, 5, 80))
        self.assertEqual(f["rounding"], "commercial_half_up")
        self.assertEqual(RULES["nova"]["malus"], {
            "threshold_gkm": 155, "rate_eur_per_gkm_over_threshold": 80
        })

    def test_ice_2026_monthly_example(self):
        f = RULES["motorbezogene_versicherungssteuer"]["ice_m1"]
        # 140 kW and 180 g/km, first registered 2026.
        p = max(f["power"]["minimum_taxable_kw"], 140 - f["power"]["threshold_kw"])
        c = max(f["co2"]["minimum_taxable_gkm"], 180 - f["co2"]["threshold_gkm"])
        self.assertAlmostEqual(p * f["power"]["rate_eur_per_kw"] +
                               c * f["co2"]["rate_eur_per_gkm"], 118.08)

    def test_bev_2026_monthly_example(self):
        f = RULES["motorbezogene_versicherungssteuer"]["bev_m1"]
        # 60 kW continuous rated power, 1450 kg: BMF example EUR 12.75.
        power = max(f["power"]["minimum_taxable_kw"], 60 - f["power"]["deduction_kw"])
        weight = max(f["weight"]["minimum_taxable_kg"], 1450 - f["weight"]["deduction_kg"])
        monthly = power * f["power"]["tiers"][0]["rate_eur_per_kw"] + (
            min(weight, 500) * f["weight"]["tiers"][0]["rate_eur_per_kg"] +
            max(0, weight - 500) * f["weight"]["tiers"][1]["rate_eur_per_kg"]
        )
        self.assertAlmostEqual(monthly, 12.75)

if __name__ == "__main__":
    unittest.main()
