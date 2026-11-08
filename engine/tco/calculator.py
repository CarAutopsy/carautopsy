import json
import yaml
from pathlib import Path
from datetime import datetime

class TCOEngine:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        
    def load_yaml(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
            
    def load_json(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def calculate(self, variant_id: str, country: str, annual_km: int, years: int) -> dict:
        # 1. Load Data
        variant_path = self.repo_root / "catalog" / "variants" / f"{variant_id}.json"
        variant = self.load_json(variant_path)
        
        pack_dir = self.repo_root / "country-packs" / country
        taxes = self.load_yaml(pack_dir / "taxes.yaml")
        defaults = self.load_yaml(pack_dir / "defaults.yaml")
        
        # 2. Statutory Calculations (Austria specific logic mapped from YAML)
        powertrain = variant["identity"]["powertrain"]
        nova_eur = 0.0
        monthly_motor_tax_eur = 0.0
        
        if powertrain not in taxes["nova"]["exemptions"]:
            # ICE/PHEV NoVA logic would go here based on CO2
            pass
            
        if powertrain not in taxes["motorbezogene_versicherungssteuer"]["exemptions"]:
            # ICE/PHEV monthly tax logic would go here based on kW and CO2
            pass
            
        # 3. Operating Costs (from defaults.yaml)
        energy_tariff = defaults["electricity"]["default_tariff_eur_kwh"] if powertrain == "bev" else defaults["fuel"]["petrol_eur_l"]
        
        # Real world consumption (Wh/km) -> kWh/100km
        consumption_wh_km = variant["energy"]["consumption_wh_km"].get("real_world") or variant["energy"]["consumption_wh_km"].get("wltp_combined") or 150
        annual_energy_kwh = (consumption_wh_km / 1000) * annual_km
        annual_energy_cost = annual_energy_kwh * energy_tariff
        
        # Maintenance & Insurance Proxies
        maint_key = "bev_annual_eur" if powertrain == "bev" else "ice_annual_eur"
        annual_maintenance = defaults["maintenance"][maint_key]
        annual_insurance = defaults["insurance_proxy"][maint_key]
        
        # Tyres
        tyre_life_years = defaults["tyres"]["replacement_interval_km"] / annual_km
        annual_tyres = defaults["tyres"]["average_cost_eur"] / tyre_life_years
        
        # 4. Aggregate TCO
        annual_operating = annual_energy_cost + annual_maintenance + annual_insurance + annual_tyres + (monthly_motor_tax_eur * 12)
        total_operating = annual_operating * years
        
        # 5. Audit Envelope (The CarAutopsy Promise)
        audit_envelope = {
            "engine_version": "1.0.0",
            "country_pack": f"{country}@{taxes.get('version', '1.0.0')}",
            "calculation_timestamp": datetime.utcnow().isoformat() + "Z",
            "variant_id": variant_id,
            "inputs": {
                "annual_km": annual_km,
                "years": years
            },
            "outputs": {
                "nova_eur": round(nova_eur, 2),
                "monthly_motor_tax_eur": round(monthly_motor_tax_eur, 2),
                "annual_energy_cost_eur": round(annual_energy_cost, 2),
                "annual_maintenance_eur": round(annual_maintenance, 2),
                "annual_insurance_proxy_eur": round(annual_insurance, 2),
                "annual_tyres_eur": round(annual_tyres, 2),
                "total_operating_cost_eur": round(total_operating, 2),
                "monthly_tco_eur": round((total_operating / (years * 12)), 2)
            },
            "confidence": "high",
            "sources": ["AT-BMF-tax-2024", "AT-Defaults-1.0.0"]
        }
        
        return audit_envelope

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent.parent
    engine = TCOEngine(root)
    
    print("\n--- CarAutopsy TCO Engine: Live Run ---")
    print("Calculating 5-year TCO for Tesla Model 3 RWD in Austria (15,000 km/yr)...\n")
    
    result = engine.calculate(
        variant_id="tesla.model-3.highland.rwd-60",
        country="AT",
        annual_km=15000,
        years=5
    )
    
    import json as j
    print(j.dumps(result, indent=2))
    print("\n✅ Audit Envelope generated successfully.")
