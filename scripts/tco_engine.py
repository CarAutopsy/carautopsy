"""Shared Austrian TCO engine and strict country-pack contract."""
import math
from pathlib import Path
import yaml
def load_country_config(root):
 root=Path(root)
 def read(name):
  with (root/f"country-packs/AT/{name}.yaml").open(encoding="utf-8") as f:return yaml.safe_load(f)
 taxes,defaults,inspections=read("taxes"),read("defaults"),read("inspections")
 validate_config(defaults,inspections);return taxes,defaults,inspections
def validate_config(d,i):
 paths=("horizon_years_default","annual_km_default","tyres.replacement_interval_km","tyres.average_cost_eur","maintenance.bev_annual_eur","maintenance.ice_annual_eur","insurance_proxy.bev_annual_eur","insurance_proxy.ice_annual_eur","electricity.default_tariff_eur_kwh","fuel.petrol_eur_l","fuel.diesel_eur_l")
 for path in paths:
  v=d
  for k in path.split("."):v=v.get(k) if isinstance(v,dict) else None
  if not isinstance(v,(int,float)) or isinstance(v,bool) or v<0:raise ValueError(f"Invalid or missing Austria TCO config: {path}")
 for path in ("horizon_years_default","annual_km_default","tyres.replacement_interval_km"):
  v=d
  for k in path.split("."):v=v[k]
  if v<=0:raise ValueError(f"Austria TCO config must be greater than zero: {path}")
 c=(i.get("defaults") or {}).get("average_cost_eur")
 if not isinstance(c,(int,float)) or isinstance(c,bool) or c<0:raise ValueError("Invalid or missing Austria inspection config: defaults.average_cost_eur")
FUEL_CONSUMPTION_DEFAULT={"ice_diesel":6.5,"ice_petrol":6.0,"hev":4.5,"phev":5.0}
def nova(v,t):
 pt=v["identity"]["powertrain"]
 if pt in t.get("nova",{}).get("exemptions",[]):return 0.0
 co2=v.get("emissions",{}).get("co2_wltp_gpkm") or 0;f=t.get("nova",{}).get("formula",{})
 if not f:return 0.0
 pct=math.floor((co2-f.get("co2_deduction_gkm",0))/f.get("divisor",1));pct=max(f.get("min_percentage",0),min(f.get("max_percentage",50),pct))
 malus=sum((co2-b["threshold_gkm"])*b["rate_eur_per_gkm_over_threshold"] for b in t.get("nova",{}).get("malus",{}).get("brackets",[]) if co2>b["threshold_gkm"])
 offers=v.get("offers") or [];gross=(offers[0].get("list_price_minor") or 0)/100 if offers else 0
 if gross<=0:return 0.0
 net=gross/((1+pct/100)*1.2);return round(max(0,net*pct/100-f.get("fixed_deduction_eur",0))+malus,2)
def motor_monthly(v,t):
 pt=v["identity"]["powertrain"];r=t.get("motorbezogene_versicherungssteuer",{})
 if pt in r.get("exemptions",[]):return 0.0
 f=r.get("formula",{})
 if not f:return 0.0
 kw=(v.get("performance",{}).get("power_w") or 0)/1000;co2=v.get("emissions",{}).get("co2_wltp_gpkm") or 0
 p=max(0,kw-f.get("power",{}).get("threshold_kw",0))*f.get("power",{}).get("rate_eur_per_kw_over_threshold",0)
 c=max(0,co2-f.get("co2",{}).get("threshold_gkm",0))*f.get("co2",{}).get("rate_eur_per_gkm_over_threshold",0);return round(p+c,2)
def calculate_tco(v,t,d,i):
 identity=v.get("identity") or {};pt=identity.get("powertrain")
 if not pt:return None
 years,km=d["horizon_years_default"],d["annual_km_default"];n=nova(v,t);mt=motor_monthly(v,t)*12*years
 if pt=="bev":
  cons=v.get("energy",{}).get("consumption_wh_km",{}) or {};wh=cons.get("real_world") or cons.get("wltp_combined") or 0
  energy=wh/1000*km*d["electricity"]["default_tariff_eur_kwh"]*years
 else:
  cons=(v.get("extensions") or {}).get("fuel_consumption_l_100km") or {};l100=cons.get("real_world") or FUEL_CONSUMPTION_DEFAULT.get(pt,6.0)
  energy=l100/100*km*d["fuel"]["diesel_eur_l" if pt=="ice_diesel" else "petrol_eur_l"]*years
 key="bev_annual_eur" if pt=="bev" else "ice_annual_eur";maint=d["maintenance"][key]*years;insurance=d["insurance_proxy"][key]*years
 tyre=d["tyres"];tyres=km*years/tyre["replacement_interval_km"]*tyre["average_cost_eur"];inspection=i["defaults"]["average_cost_eur"]*years
 total=n+mt+energy+maint+insurance+tyres+inspection;offers=v.get("offers") or []
 return {"variant_id":v.get("variant_id"),"make":identity.get("make"),"model":identity.get("model"),"variant_name":identity.get("variant_name"),"powertrain":pt,
 "power_kw":round((v.get("performance",{}).get("power_w") or 0)/1000,1),"co2_gkm":v.get("emissions",{}).get("co2_wltp_gpkm"),
 "list_price_eur":round((offers[0].get("list_price_minor") or 0)/100,2) if offers else None,"nova_eur":n,"motor_tax_monthly_eur":motor_monthly(v,t),
 "energy_5y_eur":round(energy,2),"maintenance_5y_eur":round(maint,2),"insurance_5y_eur":round(insurance,2),"tyres_5y_eur":round(tyres,2),
 "inspection_5y_eur":round(inspection,2),"total_5y_eur":round(total,2),"monthly_eur":round(total/(years*12),2),"data_confidence":(v.get("provenance") or {}).get("confidence")}
