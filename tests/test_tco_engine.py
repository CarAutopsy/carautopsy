import copy
import json
from datetime import datetime, timedelta, timezone
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tco_engine import (ENGINE_VERSION, assert_tax_pack_publishable, calculate_tco, load_country_config,
                        motor_monthly, nova, publication_artifact_is_current, publication_metadata, validate_config)

ROOT = Path(__file__).resolve().parents[1]


class TcoConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t, cls.d, cls.i = load_country_config(ROOT)

    def vehicle(self, pt):
        v = {
            "variant_id": "test",
            "identity": {"make": "Test", "model": "Car", "powertrain": pt, "vehicle_class": "M1"},
            "registration": {"first_registration_date": "2026-01-15"},
            "performance": {"power_w": 100000, "combustion_engine_power_w": 140000,
                            "electric_motor_continuous_power_w": 60000},
            "dimensions": {"own_weight_kg": 1450, "max_permissible_mass_kg": 2000},
            "emissions": {"co2_wltp_gpkm": 180, "co2_wltp_weighted_combined_gpkm": 30},
            "offers": [{"purchase_price_excl_vat_eur": 20000, "list_price_minor": 2400000}],
        }
        if pt == "bev":
            v["energy"] = {"consumption_wh_km": {"real_world": 180}}
        else:
            v["extensions"] = {"fuel_consumption_l_100km": {"real_world": 6}}
        return v

    def test_shared_engine_contract_has_valid_freshness_policy(self):
        contract = json.loads((ROOT / "tco-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["engine_version"], ENGINE_VERSION)
        self.assertGreater(contract["max_artifact_age_days"], 0)
        self.assertGreaterEqual(contract["max_future_skew_minutes"], 0)

    def test_publication_artifact_is_current_only_when_metadata_matches_and_is_fresh(self):
        now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        candidate = {
            "results": [{"variant_id": "test", "monthly_eur": 1}],
            "summary": {"variants": 1},
            "envelope": {
                **publication_metadata(self.t),
                "generated_utc": now.isoformat(),
                "currency": "EUR",
            },
        }
        fresh = copy.deepcopy(candidate)
        fresh["envelope"]["generated_utc"] = (now - timedelta(days=1)).isoformat()
        self.assertTrue(publication_artifact_is_current(fresh, candidate, now=now))

        expired = copy.deepcopy(candidate)
        expired["envelope"]["generated_utc"] = (now - timedelta(days=8)).isoformat()
        self.assertFalse(publication_artifact_is_current(expired, candidate, now=now))

        wrong_metadata = copy.deepcopy(fresh)
        wrong_metadata["envelope"]["country_pack_status"] = "verified"
        self.assertFalse(publication_artifact_is_current(wrong_metadata, candidate, now=now))

        malformed_timestamp = copy.deepcopy(fresh)
        malformed_timestamp["envelope"]["generated_utc"] = "not-a-date"
        self.assertFalse(publication_artifact_is_current(malformed_timestamp, candidate, now=now))

        space_separated_timestamp = copy.deepcopy(fresh)
        space_separated_timestamp["envelope"]["generated_utc"] = "2026-11-14 12:00:00+00:00"
        self.assertFalse(publication_artifact_is_current(space_separated_timestamp, candidate, now=now))

        impossible_calendar_date = copy.deepcopy(fresh)
        impossible_calendar_date["envelope"]["generated_utc"] = "2026-11-31T12:00:00Z"
        self.assertFalse(publication_artifact_is_current(impossible_calendar_date, candidate, now=now))

        invalid_timezone_minutes = copy.deepcopy(fresh)
        invalid_timezone_minutes["envelope"]["generated_utc"] = "2026-11-14T12:00:00+00:60"
        self.assertFalse(publication_artifact_is_current(invalid_timezone_minutes, candidate, now=now))

        boolean_summary_count = copy.deepcopy(fresh)
        boolean_summary_count["summary"]["variants"] = True
        self.assertFalse(publication_artifact_is_current(boolean_summary_count, candidate, now=now))

        boolean_result_cost = copy.deepcopy(fresh)
        boolean_result_cost["results"][0]["monthly_eur"] = True
        self.assertFalse(publication_artifact_is_current(boolean_result_cost, candidate, now=now))

    def test_publication_artifact_refreshes_when_results_or_summary_change(self):
        now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        candidate = {
            "results": [{"variant_id": "test", "monthly_eur": 100}],
            "summary": {"variants": 1},
            "envelope": {**publication_metadata(self.t), "generated_utc": now.isoformat()},
        }
        changed = copy.deepcopy(candidate)
        changed["results"][0]["monthly_eur"] = 101
        self.assertFalse(publication_artifact_is_current(candidate, changed, now=now))
        changed = copy.deepcopy(candidate)
        changed["summary"]["variants"] = 2
        self.assertFalse(publication_artifact_is_current(candidate, changed, now=now))

    def test_publication_metadata_tracks_current_tax_pack(self):
        metadata = publication_metadata(self.t)
        self.assertEqual(metadata["engine_version"], ENGINE_VERSION)
        self.assertEqual(metadata["country_pack"], f"AT@{self.t['version']}")
        self.assertEqual(metadata["country_pack_status"], "draft")

    def test_publication_metadata_rejects_missing_contract_fields(self):
        for taxes in ({}, {"version": "1.2.0"}, {"status": "draft"}):
            with self.assertRaises(ValueError):
                publication_metadata(taxes)

    def test_pack_validates(self):
        validate_config(self.d, self.i)

    def test_draft_tax_pack_blocks_tco_publication(self):
        with self.assertRaisesRegex(ValueError, "TCO publication is disabled"):
            calculate_tco(self.vehicle("bev"), self.t, self.d, self.i)

    def test_bev_assumptions_change_outputs(self):
        v = self.vehicle("bev")
        base = calculate_tco(v, self.t, self.d, self.i, allow_draft=True)
        d = copy.deepcopy(self.d)
        d["electricity"]["default_tariff_eur_kwh"] *= 2
        d["maintenance"]["bev_annual_eur"] *= 2
        d["insurance_proxy"]["bev_annual_eur"] *= 2
        d["tyres"]["average_cost_eur"] *= 2
        x = calculate_tco(v, self.t, d, self.i, allow_draft=True)
        for key in ("energy_5y_eur", "maintenance_5y_eur", "insurance_5y_eur", "tyres_5y_eur"):
            self.assertGreater(x[key], base[key])

    def test_wltp_only_fuel_consumption_is_used_without_default(self):
        v = self.vehicle("ice_petrol")
        v["extensions"]["fuel_consumption_l_100km"] = {"wltp_combined": 8.0}
        result = calculate_tco(v, self.t, self.d, self.i, allow_draft=True)
        expected = 8.0 / 100 * self.d["annual_km_default"] * self.d["fuel"]["petrol_eur_l"] * self.d["horizon_years_default"]
        self.assertAlmostEqual(result["energy_5y_eur"], round(expected, 2))

    def test_missing_fuel_consumption_does_not_use_a_hard_coded_default(self):
        v = self.vehicle("ice_petrol")
        v["extensions"]["fuel_consumption_l_100km"] = {}
        with self.assertRaisesRegex(ValueError, "finite positive fuel consumption"):
            calculate_tco(v, self.t, self.d, self.i, allow_draft=True)

    def test_ice_assumptions_change_outputs(self):
        v = self.vehicle("ice_petrol")
        base = calculate_tco(v, self.t, self.d, self.i, allow_draft=True)
        d = copy.deepcopy(self.d)
        d["fuel"]["petrol_eur_l"] *= 2
        d["maintenance"]["ice_annual_eur"] *= 2
        d["insurance_proxy"]["ice_annual_eur"] *= 2
        x = calculate_tco(v, self.t, d, self.i, allow_draft=True)
        for key in ("energy_5y_eur", "maintenance_5y_eur", "insurance_5y_eur"):
            self.assertGreater(x[key], base[key])

    def test_horizon_and_mileage_are_configurable(self):
        v = self.vehicle("bev")
        base = calculate_tco(v, self.t, self.d, self.i, allow_draft=True)
        d = copy.deepcopy(self.d)
        d["horizon_years_default"] = 10
        d["annual_km_default"] = 20000
        self.assertGreater(calculate_tco(v, self.t, d, self.i, allow_draft=True)["total_5y_eur"], base["total_5y_eur"])

    def test_missing_assumption_fails_closed(self):
        d = copy.deepcopy(self.d)
        del d["electricity"]
        with self.assertRaisesRegex(ValueError, "electricity.default_tariff_eur_kwh"):
            validate_config(d, self.i)

    def test_inspection_pack_controls_cost(self):
        i = copy.deepcopy(self.i)
        i["defaults"]["average_cost_eur"] = 70
        self.assertEqual(calculate_tco(self.vehicle("bev"), self.t, self.d, i, allow_draft=True)["inspection_5y_eur"], 350)

    def test_missing_registration_or_tax_inputs_fail_closed(self):
        v = self.vehicle("ice_petrol")
        del v["registration"]
        with self.assertRaisesRegex(ValueError, "first_registration_date"):
            motor_monthly(v, self.t)
        v = self.vehicle("bev")
        del v["dimensions"]["own_weight_kg"]
        with self.assertRaisesRegex(ValueError, "own_weight_kg"):
            motor_monthly(v, self.t)

    def test_motor_tax_uses_first_registration_year(self):
        v = self.vehicle("ice_petrol")
        v["registration"]["first_registration_date"] = "2025-01-15"
        self.assertAlmostEqual(motor_monthly(v, self.t), 115.20)
        v["registration"]["first_registration_date"] = "2026-01-15"
        self.assertAlmostEqual(motor_monthly(v, self.t), 118.08)

    def test_m1_mass_above_3500kg_is_unsupported(self):
        v = self.vehicle("ice_petrol")
        v["dimensions"]["max_permissible_mass_kg"] = 3600
        with self.assertRaisesRegex(ValueError, "up to 3,500 kg"):
            motor_monthly(v, self.t)

    def test_bev_rules_apply_to_existing_vehicles_from_2025(self):
        v = self.vehicle("bev")
        v["registration"]["first_registration_date"] = "2023-06-01"
        self.assertAlmostEqual(motor_monthly(v, self.t), 12.75)

    def test_bev_all_power_and_weight_tiers(self):
        v = self.vehicle("bev")
        self.assertAlmostEqual(motor_monthly(v, self.t), 12.75)
        v["performance"]["electric_motor_continuous_power_w"] = 210000
        v["dimensions"]["own_weight_kg"] = 2200
        self.assertAlmostEqual(motor_monthly(v, self.t), 97.75)

    def test_phev_uses_combustion_power_and_weighted_co2(self):
        v = self.vehicle("phev")
        v["performance"]["combustion_engine_power_w"] = 120000
        self.assertAlmostEqual(motor_monthly(v, self.t), 48.24)
        v["emissions"]["co2_wltp_weighted_combined_gpkm"] = None
        with self.assertRaisesRegex(ValueError, "weighted_combined"):
            motor_monthly(v, self.t)

    def test_nova_uses_half_up_and_malus_and_explicit_net_base(self):
        v = self.vehicle("ice_petrol")
        v["emissions"]["co2_wltp_gpkm"] = 165
        self.assertAlmostEqual(nova(v, self.t), 3450.0)
        del v["offers"][0]["purchase_price_excl_vat_eur"]
        with self.assertRaisesRegex(ValueError, "purchase_price_excl_vat_eur"):
            nova(v, self.t)

    def test_fcev_motor_tax_does_not_assume_exemption(self):
        v = self.vehicle("fcev")
        with self.assertRaisesRegex(ValueError, "unsupported for powertrain"):
            motor_monthly(v, self.t)


    def test_publish_gate_rejects_draft_pack(self):
        with self.assertRaisesRegex(ValueError, "requires status 'verified'"):
            assert_tax_pack_publishable(self.t)

    def test_publish_gate_rejects_incomplete_schedules(self):
        verified = copy.deepcopy(self.t)
        verified["status"] = "verified"
        del verified["nova"]["annual_rules"]
        with self.assertRaisesRegex(ValueError, "NoVA annual_rules"):
            assert_tax_pack_publishable(verified)

    def test_legacy_engine_adapter_fails_closed_on_draft_pack(self):
        sys.path.insert(0, str(ROOT))
        from engine.tco.calculator import TCOEngine
        with self.assertRaisesRegex(ValueError, "TCO publication is disabled"):
            TCOEngine(ROOT).calculate("tesla.model-3.highland.rwd-60", "AT", 15000, 5)

    def test_legacy_builder_is_non_mutating(self):
        import subprocess
        result = subprocess.run([sys.executable, str(ROOT / "build_engine.py")],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No files changed", result.stdout)

if __name__ == "__main__":
    unittest.main()
