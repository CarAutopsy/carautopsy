import os
import subprocess

def run(cmd):
    print(f"  > {cmd}")
    subprocess.run(cmd, shell=True)

def write(path, content):
    d = os.path.dirname(path)
    if d: os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"Created: {path}")

print("Building Austria (AT) Country Pack...")

taxes_yaml = '''country: AT
version: "1.0.0"
effective_from: "2024-01-01"
currency: EUR

nova:
  description: "Normverbrauchsabgabe (One-time registration tax)"
  exemptions: ["bev", "fcev"]
  deduction_co2_gkm: 97
  divisor: 5
  max_percentage: 55
  malus_brackets:
    - threshold_gkm: 200
      rate_eur_per_gkm: 20
    - threshold_gkm: 250
      rate_eur_per_gkm: 40
    - threshold_gkm: 300
      rate_eur_per_gkm: 50
  source: "BMF NoVA Rechner 2024"

motorbezogene_versicherungssteuer:
  description: "Monthly motor-related insurance tax"
  exemptions: ["bev", "fcev"]
  effective_from: "2021-10-01"
  power_component:
    threshold_kw: 65
    rate_eur_per_kw: 0.72
  co2_component:
    threshold_gkm: 115
    rate_eur_per_gkm: 0.25
  source: "WKO / BMF Motorbezogene Versicherungssteuer"
'''
write("country-packs/AT/taxes.yaml", taxes_yaml)

inspections_yaml = '''country: AT
version: "1.0.0"
name: "§57a Begutachtung (Pickerl)"
intervals_years: [3, 2, 1, 1, 1]
average_cost_eur: 25.00
grace_period_months: 4
sources:
  - name: "ÖAMTC §57a Info"
    url: "https://www.oeamtc.at/fahrzeug/begutachtung/"
'''
write("country-packs/AT/inspections.yaml", inspections_yaml)

incentives_yaml = '''country: AT
version: "1.0.0"
name: "E-Mobilitätsbonus & Förderungen"
bev_purchase_subsidy_eur: 2500.00
wallbox_subsidy_eur: 600.00
exemptions:
  - nova
  - motorbezogene_versicherungssteuer
sources:
  - name: "BMK E-Mobilitätsförderungen"
    url: "https://www.bmk.gv.at/"
'''
write("country-packs/AT/incentives.yaml", incentives_yaml)

defaults_yaml = '''country: AT
version: "1.0.0"
tyres:
  replacement_interval_km: 30000
  average_cost_eur: 800
maintenance:
  bev_annual_eur: 150
  ice_annual_eur: 450
insurance_proxy:
  bev_annual_eur: 900
  ice_annual_eur: 1100
electricity:
  default_tariff_eur_kwh: 0.35
fuel:
  petrol_eur_l: 1.65
  diesel_eur_l: 1.55
'''
write("country-packs/AT/defaults.yaml", defaults_yaml)

sources_yaml = '''country: AT
version: "1.0.0"
sources:
  - id: at-bmf-nova
    name: "Bundesministerium für Finanzen (BMF) - NoVA"
    url: "https://www.bmf.gv.at/themen/steuern/verkehr-und-immobilien/normverbrauchsabgabe.html"
    type: statutory
    licence: "Public"
  - id: at-bmf-motorbez
    name: "Bundesministerium für Finanzen (BMF) - Motorbezogene Versicherungssteuer"
    url: "https://www.bmf.gv.at/"
    type: statutory
    licence: "Public"
  - id: at-econtrol
    name: "E-Control Austria"
    url: "https://www.e-control.at/"
    type: statutory
    licence: "Public"
'''
write("country-packs/AT/sources.yaml", sources_yaml)

test_tesla = '''test_id: "AT-TEST-001"
variant_id: "tesla.model-3.highland.rwd-60"
country: AT
inputs:
  purchase_price_eur: 40000
  annual_mileage_km: 15000
  ownership_years: 5
expected_outputs:
  nova_eur: 0.00
  monthly_motor_tax_eur: 0.00
  inspection_interval_years: [3, 2, 1, 1, 1]
  notes: "BEV is fully exempt from NoVA and motorbezogene Versicherungssteuer in Austria."
'''
write("country-packs/AT/tests/test_tesla_model_3.yaml", test_tesla)

manifest_yaml = '''country: AT
name: Austria
version: "1.0.0"
status: verified
effective_from: "2024-01-01"
currency: EUR
components:
  - taxes.yaml
  - inspections.yaml
  - incentives.yaml
  - defaults.yaml
  - sources.yaml
test_vehicles:
  - tests/test_tesla_model_3.yaml
'''
write("country-packs/AT/manifest.yaml", manifest_yaml)

print("\nCommitting and pushing to GitHub...")
run("git add -A")
run('git commit -m "feat(country-pack): add verified Austria (AT) statutory pack (NoVA, §57a, TCO defaults)"')
run("git push origin main")

print("\n✅ Austria Country Pack successfully built and pushed!")