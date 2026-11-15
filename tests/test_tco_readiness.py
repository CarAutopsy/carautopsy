import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_tco_readiness import validate_variant_readiness, validate_catalog_readiness


def vehicle(powertrain="ice_petrol"):
    record = {
        "variant_id": "test.vehicle",
        "identity": {"powertrain": powertrain, "vehicle_class": "M1"},
        "registration": {"first_registration_date": "2026-01-01"},
        "dimensions": {"max_permissible_mass_kg": 2000},
        "emissions": {"co2_wltp_gpkm": 150},
        "performance": {"combustion_engine_power_w": 100000},
        "extensions": {"fuel_consumption_l_100km": {"real_world": 6.0}},
        "offers": [{"purchase_price_excl_vat_eur": 20000}],
    }
    if powertrain == "bev":
        record["performance"] = {"electric_motor_continuous_power_w": 100000}
        record["dimensions"]["own_weight_kg"] = 1800
        record["energy"] = {"consumption_wh_km": {"real_world": 160}}
        record.pop("extensions")
        record.pop("offers")
        record["emissions"] = {"co2_wltp_gpkm": 0}
    if powertrain == "phev":
        record["emissions"]["co2_wltp_weighted_combined_gpkm"] = 30
    return record


class TcoReadinessTests(unittest.TestCase):
    def test_complete_ice_record_is_ready(self):
        self.assertEqual(validate_variant_readiness(vehicle()), [])

    def test_complete_bev_record_does_not_require_nova_price_or_combustion_power(self):
        self.assertEqual(validate_variant_readiness(vehicle("bev")), [])

    def test_phev_requires_weighted_co2(self):
        record = vehicle("phev")
        del record["emissions"]["co2_wltp_weighted_combined_gpkm"]
        self.assertIn("emissions.co2_wltp_weighted_combined_gpkm",
                      validate_variant_readiness(record))

    def test_missing_tax_inputs_are_reported_without_defaults(self):
        record = vehicle()
        del record["registration"]
        del record["performance"]["combustion_engine_power_w"]
        issues = validate_variant_readiness(record)
        self.assertIn("registration.first_registration_date", issues)
        self.assertIn("performance.combustion_engine_power_w", issues)

    def test_unsupported_vehicle_class_and_powertrain_fail_readiness(self):
        record = vehicle()
        record["identity"]["vehicle_class"] = "N1"
        record["identity"]["powertrain"] = "unknown"
        issues = validate_variant_readiness(record)
        self.assertTrue(any(x.startswith("unsupported identity.vehicle_class") for x in issues))
        self.assertTrue(any(x.startswith("unsupported identity.powertrain") for x in issues))

    def test_catalog_reports_invalid_json_and_sparse_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.json").write_text("{", encoding="utf-8")
            (root / "sparse.json").write_text(json.dumps({"variant_id": "sparse"}), encoding="utf-8")
            findings = validate_catalog_readiness(root)
        self.assertEqual(len(findings), 2)
        self.assertTrue(any("invalid JSON" in issue for f in findings for issue in f["issues"]))
        self.assertTrue(any("identity.powertrain" in issue for f in findings for issue in f["issues"]))

    def test_strict_cli_fails_but_advisory_cli_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "sparse.json").write_text(json.dumps({"variant_id": "sparse"}), encoding="utf-8")
            base = [sys.executable, str(ROOT / "scripts" / "validate_tco_readiness.py"),
                    "--catalog-dir", tmp]
            advisory = subprocess.run(base, capture_output=True, text=True, check=False)
            strict = subprocess.run(base + ["--strict"], capture_output=True, text=True, check=False)
        self.assertEqual(advisory.returncode, 0, advisory.stderr)
        self.assertIn("need input completion", advisory.stdout)
        self.assertEqual(strict.returncode, 1)


if __name__ == "__main__":
    unittest.main()
