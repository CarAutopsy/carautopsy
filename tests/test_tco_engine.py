import copy,unittest
from pathlib import Path
from tco_engine import calculate_tco,load_country_config,validate_config
ROOT=Path(__file__).resolve().parents[1]
class TcoConfigTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.t,cls.d,cls.i=load_country_config(ROOT)
 def vehicle(self,pt):
  v={"variant_id":"test","identity":{"make":"Test","model":"Car","powertrain":pt},"performance":{"power_w":100000},"emissions":{"co2_wltp_gpkm":120},"offers":[]}
  if pt=="bev":v["energy"]={"consumption_wh_km":{"real_world":180}}
  else:v["extensions"]={"fuel_consumption_l_100km":{"real_world":6}}
  return v
 def test_pack_validates(self):validate_config(self.d,self.i)
 def test_bev_assumptions_change_outputs(self):
  v=self.vehicle("bev");base=calculate_tco(v,self.t,self.d,self.i);d=copy.deepcopy(self.d)
  d["electricity"]["default_tariff_eur_kwh"]*=2;d["maintenance"]["bev_annual_eur"]*=2;d["insurance_proxy"]["bev_annual_eur"]*=2;d["tyres"]["average_cost_eur"]*=2
  x=calculate_tco(v,self.t,d,self.i)
  for k in ("energy_5y_eur","maintenance_5y_eur","insurance_5y_eur","tyres_5y_eur"):self.assertGreater(x[k],base[k])
 def test_ice_assumptions_change_outputs(self):
  v=self.vehicle("ice_petrol");base=calculate_tco(v,self.t,self.d,self.i);d=copy.deepcopy(self.d)
  d["fuel"]["petrol_eur_l"]*=2;d["maintenance"]["ice_annual_eur"]*=2;d["insurance_proxy"]["ice_annual_eur"]*=2
  x=calculate_tco(v,self.t,d,self.i)
  for k in ("energy_5y_eur","maintenance_5y_eur","insurance_5y_eur"):self.assertGreater(x[k],base[k])
 def test_horizon_and_mileage_are_configurable(self):
  v=self.vehicle("bev");base=calculate_tco(v,self.t,self.d,self.i);d=copy.deepcopy(self.d);d["horizon_years_default"]=10;d["annual_km_default"]=20000
  self.assertGreater(calculate_tco(v,self.t,d,self.i)["total_5y_eur"],base["total_5y_eur"])
 def test_missing_assumption_fails_closed(self):
  d=copy.deepcopy(self.d);del d["electricity"]
  with self.assertRaisesRegex(ValueError,"electricity.default_tariff_eur_kwh"):validate_config(d,self.i)
 def test_inspection_pack_controls_cost(self):
  i=copy.deepcopy(self.i);i["defaults"]["average_cost_eur"]=70
  self.assertEqual(calculate_tco(self.vehicle("bev"),self.t,self.d,i)["inspection_5y_eur"],350)
if __name__=="__main__":unittest.main()
