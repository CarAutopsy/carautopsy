"""Regression tests exercise the actual Austrian tax engine, not just YAML values."""
import sys
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tco_engine import motor_monthly, nova

RULES = yaml.safe_load((ROOT / "country-packs/AT/taxes.yaml").read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((ROOT / "country-packs/AT/manifest.yaml").read_text(encoding="utf-8"))
INCENTIVES = yaml.safe_load((ROOT / "country-packs/AT/incentives.yaml").read_text(encoding="utf-8"))


def vehicle(pt="ice_petrol", power_kw=140, co2=180, date="2026-01-15"):
    return {
        "identity": {"powertrain": pt, "vehicle_class": "M1"},
        "registration": {"first_registration_date": date},
        "performance": {"combustion_engine_power_w": power_kw * 1000,
                        "electric_motor_continuous_power_w": power_kw * 1000},
        "dimensions": {"own_weight_kg": 1450, "max_permissible_mass_kg": 2000},
        "emissions": {"co2_wltp_gpkm": co2, "co2_wltp_weighted_combined_gpkm": co2},
        "offers": [{"purchase_price_excl_vat_eur": 10000}],
    }


class Austrian2026RuleTests(unittest.TestCase):
    def test_pack_remains_draft(self):
        self.assertEqual(RULES["status"], "draft")
        self.assertEqual(MANIFEST["status"], "draft")

    def test_incentives_do_not_claim_bev_motor_tax_exemption(self):
        exemptions = INCENTIVES.get("rules", {}).get("exemptions", [])
        self.assertNotIn("motorbezogene_versicherungssteuer", exemptions)

    def test_legacy_pack_builder_is_non_mutating_and_consistent(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, str(ROOT / "build_at_country_pack.py")],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No files changed", result.stdout)

    def test_ice_2026_bmf_example(self):
        self.assertAlmostEqual(motor_monthly(vehicle(), RULES), 118.08)

    def test_ice_2025_uses_its_own_thresholds(self):
        self.assertAlmostEqual(motor_monthly(vehicle(date="2025-01-15"), RULES), 115.20)

    def test_bev_bmf_examples_and_top_tiers(self):
        v = vehicle("bev", 60, 0)
        self.assertAlmostEqual(motor_monthly(v, RULES), 12.75)
        v = vehicle("bev", 210, 0)
        v["dimensions"]["own_weight_kg"] = 2200
        self.assertAlmostEqual(motor_monthly(v, RULES), 97.75)

    def test_phev_bmf_2026_example(self):
        v = vehicle("phev", 120, 30)
        self.assertAlmostEqual(motor_monthly(v, RULES), 48.24)

    def test_nova_2026_rounding_and_malus(self):
        v = vehicle(co2=165)
        # 14.8% is commercially rounded to 15%; €10,000 * 15% + €800 - €350.
        self.assertAlmostEqual(nova(v, RULES), 1950.0)

    def test_nova_2027_uses_year_specific_deduction_and_same_155_malus(self):
        v = vehicle(co2=165, date="2027-01-15")
        # (165 - 88) / 5 = 15.4%, rounded to 15%; malus remains above 155.
        self.assertAlmostEqual(nova(v, RULES), 1950.0)

    def test_nova_pre_july_2025_fails_closed(self):
        v = vehicle(date="2025-06-30")
        with self.assertRaisesRegex(ValueError, "before 2025-07-01"):
            nova(v, RULES)


if __name__ == "__main__":
    unittest.main()
