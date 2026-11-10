import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tco_engine import calculate_tco, load_country_config, motor_monthly, nova, validate_config

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
            "performance": {"power_w": 100000, "combustion_engine_power_w": 100000,
                            "electric_motor_continuous_power_w": 60000},
            "dimensions": {"own_weight_kg": 1450},
            "emissions": {"co2_wltp_gpkm": 120, "co2_wltp_weighted_combined_gpkm": 30},
            "offers": [{"purchase_price_excl_vat_eur": 20000, "list_price_minor": 2400000}],
        }
        if pt == "bev":
            v["energy"] = {"consumption_wh_km": {"real_world": 180}}
        else:
            v["extensions"] = {"fuel_consumption_l_100km": {"real_world": 6}}
        return v

    def test_pack_validates(self):
        validate_config(self.d, self.i)

    def test_bev_assumptions_change_outputs(self):
        v = self.vehicle("bev")
        base = calculate_tco(v, self.t, self.d, self.i)
        d = copy.deepcopy(self.d)
        d["electricity"]["default_tariff_eur_kwh"] *= 2
        d["maintenance"]["bev_annual_eur"] *= 2
        d["insurance_proxy"]["bev_annual_eur"] *= 2
        d["tyres"]["average_cost_eur"] *= 2
        x = calculate_tco(v, self.t, d, self.i)
        for key in ("energy_5y_eur", "maintenance_5y_eur", "insurance_5y_eur", "tyres_5y_eur"):
            self.assertGreater(x[key], base[key])

    def test_ice_assumptions_change_outputs(self):
        v = self.vehicle("ice_petrol")
        base = calculate_tco(v, self.t, self.d, self.i)
        d = copy.deepcopy(self.d)
        d["fuel"]["petrol_eur_l"] *= 2
        d["maintenance"]["ice_annual_eur"] *= 2
        d["insurance_proxy"]["ice_annual_eur"] *= 2
        x = calculate_tco(v, self.t, d, self.i)
        for key in ("energy_5y_eur", "maintenance_5y_eur", "insurance_5y_eur"):
            self.assertGreater(x[key], base[key])

    def test_horizon_and_mileage_are_configurable(self):
        v = self.vehicle("bev")
        base = calculate_tco(v, self.t, self.d, self.i)
        d = copy.deepcopy(self.d)
        d["horizon_years_default"] = 10
        d["annual_km_default"] = 20000
        self.assertGreater(calculate_tco(v, self.t, d, self.i)["total_5y_eur"], base["total_5y_eur"])

    def test_missing_assumption_fails_closed(self):
        d = copy.deepcopy(self.d)
        del d["electricity"]
        with self.assertRaisesRegex(ValueError, "electricity.default_tariff_eur_kwh"):
            validate_config(d, self.i)

    def test_inspection_pack_controls_cost(self):
        i = copy.deepcopy(self.i)
        i["defaults"]["average_cost_eur"] = 70
        self.assertEqual(calculate_tco(self.vehicle("bev"), self.t, self.d, i)["inspection_5y_eur"], 350)

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

    def test_bev_all_power_and_weight_tiers(self):
        v = self.vehicle("bev")
        self.assertAlmostEqual(motor_monthly(v, self.t), 12.75)
        v["performance"]["electric_motor_continuous_power_w"] = 210000
        v["dimensions"]["own_weight_kg"] = 2200
        self.assertAlmostEqual(motor_monthly(v, self.t), 97.75)

    def test_phev_uses_combustion_power_and_weighted_co2(self):
        v = self.vehicle("phev")
        self.assertAlmostEqual(motor_monthly(v, self.t), 48.24)
        v["emissions"]["co2_wltp_weighted_combined_gpkm"] = None
        with self.assertRaisesRegex(ValueError, "weighted_combined"):
            motor_monthly(v, self.t)

    def test_nova_uses_half_up_and_malus_and_explicit_net_base(self):
        v = self.vehicle("ice_petrol")
        v["emissions"]["co2_wltp_gpkm"] = 165
        self.assertAlmostEqual(nova(v, self.t), 1950.0)
        del v["offers"][0]["purchase_price_excl_vat_eur"]
        with self.assertRaisesRegex(ValueError, "purchase_price_excl_vat_eur"):
            nova(v, self.t)

    def test_fcev_motor_tax_does_not_assume_exemption(self):
        v = self.vehicle("fcev")
        with self.assertRaisesRegex(ValueError, "unsupported for powertrain"):
            motor_monthly(v, self.t)


if __name__ == "__main__":
    unittest.main()
