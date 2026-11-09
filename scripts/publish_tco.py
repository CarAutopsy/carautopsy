import json, math, subprocess, sys, re
from pathlib import Path
from datetime import datetime, timezone
import yaml

ROOT = Path.cwd()

# THE NUCLEAR OPTION: Destroys all invisible characters in keys
def clean(o):
    if isinstance(o, dict):
        return {re.sub(r'[^a-zA-Z0-9_]', '', str(k)): clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(i) for i in o]
    if isinstance(o, str): return o.strip()
    return o

def load(p):
    with open(p, encoding="utf-8") as f:
        return clean(json.load(f) if p.suffix == ".json" else yaml.safe_load(f))

taxes = load(ROOT / "country-packs/AT/taxes.yaml")
defaults = load(ROOT / "country-packs/AT/defaults.yaml")

FUEL_DEFAULT = {"ice_diesel": 6.5, "ice_petrol": 6.0, "hev": 4.5, "phev": 5.0}
MAINT = {"bev": 150, "phev": 350, "hev": 400, "ice_petrol": 450, "ice_diesel": 450}

def nova(v):
    pt = v["identity"]["powertrain"]
    if pt in taxes.get("nova", {}).get("exemptions", []): return 0.0
    co2 = v.get("emissions", {}).get("co2_wltp_gpkm") or 0
    f = taxes.get("nova", {}).get("formula", {})
    if not f: return 0.0
    pct = math.floor((co2 - f.get("co2_deduction_gkm", 0)) / f.get("divisor", 1))
    pct = max(f.get("min_percentage", 0), min(f.get("max_percentage", 50), pct))
    malus = sum((co2 - b["threshold_gkm"]) * b["rate_eur_per_gkm_over_threshold"]
                for b in taxes.get("nova", {}).get("malus", {}).get("brackets", []) if co2 > b["threshold_gkm"])
    offers = v.get("offers") or []
    gross = (offers[0].get("list_price_minor") or 0) / 100.0 if offers else 0.0
    if gross <= 0: return 0.0
    net = gross / ((1 + pct / 100.0) * 1.20)
    return round(max(0.0, net * pct / 100.0 - f.get("fixed_deduction_eur", 0)) + malus, 2)

def motor_monthly(v):
    pt = v["identity"]["powertrain"]
    if pt in taxes.get("motorbezogene_versicherungssteuer", {}).get("exemptions", []): return 0.0
    f = taxes.get("motorbezogene_versicherungssteuer", {}).get("formula", {})
    if not f: return 0.0
    kw = (v.get("performance", {}).get("power_w") or 0) / 1000.0
    co2 = v.get("emissions", {}).get("co2_wltp_gpkm") or 0
    p = max(0.0, kw - f.get("power", {}).get("threshold_kw", 0)) * f.get("power", {}).get("rate_eur_per_kw_over_threshold", 0)
    c = max(0.0, co2 - f.get("co2", {}).get("threshold_gkm", 0)) * f.get("co2", {}).get("rate_eur_per_gkm_over_threshold", 0)
    return round(p + c, 2)

def tco(v):
    identity = v.get("identity") or {}
    pt = identity.get("powertrain")
    if not pt:
        return None # Skip malformed vehicles
        
    yrs = defaults.get("horizon_years_default", 5)
    km = defaults.get("annual_km_default", 15000)
    
    n = nova(v); mt = motor_monthly(v) * 12 * yrs
    
    if pt == "bev":
        energy_dict = v.get("energy", {}).get("consumption_wh_km", {}) or {}
        wh = energy_dict.get("real_world") or energy_dict.get("wltp_combined") or 0
        energy = (wh / 1000.0) * km * defaults.get("energy", {}).get("electricity_tariff_eur_kwh", 0.35) * yrs
    else:
        l100 = (v.get("extensions") or {}).get("fuel_consumption_l_100km") or {}
        l100 = l100.get("real_world") or FUEL_DEFAULT.get(pt, 6.0)
        price = defaults.get("energy", {}).get("diesel_eur_l", 1.55) if pt == "ice_diesel" else defaults.get("energy", {}).get("petrol_eur_l", 1.65)
        energy = (l100 / 100.0) * km * price * yrs
        
    maint = MAINT.get(pt, 450) * yrs
    ins = defaults.get("insurance_proxy_annual_eur", {}).get("bev" if pt == "bev" else "ice", 1100) * yrs
    tyres = (km * yrs / defaults.get("tyres", {}).get("interval_km", 30000)) * defaults.get("tyres", {}).get("set_cost_eur", 800)
    insp = defaults.get("inspection_annual_proxy_eur", 35) * yrs
    total = n + mt + energy + maint + ins + tyres + insp
    offers = v.get("offers") or []
    return {
        "variant_id": v.get("variant_id"),
        "make": identity.get("make"),
        "model": identity.get("model"),
        "variant_name": identity.get("variant_name"),
        "powertrain": pt,
        "power_kw": round((v.get("performance", {}).get("power_w") or 0) / 1000.0, 1),
        "co2_gkm": v.get("emissions", {}).get("co2_wltp_gpkm"),
        "list_price_eur": round((offers[0].get("list_price_minor") or 0) / 100.0, 2) if offers else None,
        "nova_eur": n,
        "motor_tax_monthly_eur": motor_monthly(v),
        "energy_5y_eur": round(energy, 2),
        "maintenance_5y_eur": round(maint, 2),
        "insurance_5y_eur": round(ins, 2),
        "tyres_5y_eur": round(tyres, 2),
        "inspection_5y_eur": round(insp, 2),
        "total_5y_eur": round(total, 2),
        "monthly_eur": round(total / (yrs * 12), 2),
        "data_confidence": (v.get("provenance") or {}).get("confidence"),
    }

results = []
for p in sorted((ROOT / "catalog" / "variants").glob("*.json")):
    try:
        r = tco(load(p))
        if r:
            results.append(r)
    except Exception as e:
        print(f"WARNING skipped {p.name}: {e}")

bevs = [r for r in results if r["powertrain"] == "bev"]
others = [r for r in results if r["powertrain"] != "bev"]
summary = {
    "variants": len(results),
    "bev_avg_monthly_eur": round(sum(r["monthly_eur"] for r in bevs) / len(bevs), 2) if bevs else None,
    "ice_avg_monthly_eur": round(sum(r["monthly_eur"] for r in others) / len(others), 2) if others else None,
}

payload = {
    "results": results,
    "summary": summary,
    "envelope": {
        "engine_version": "0.3.1",
        "country_pack": "AT@1.0.0",
        "assumptions_version": "AT-defaults@1.0.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "currency": "EUR",
        "horizon_years": defaults.get("horizon_years_default", 5),
        "annual_km": defaults.get("annual_km_default", 15000),
        "sources": ["AT-BMF-tax-2024", "AT-OEAMTC-57a", "AT-defaults-assumptions-1.0.0"],
        "note": "Operating + statutory costs only; excludes depreciation and financing.",
    },
}

out = ROOT / "apps" / "web" / "public" / "data" / "autopsies.json"
new_results = json.dumps(results, sort_keys=True)
if out.exists():
    try:
        old = json.loads(out.read_text(encoding="utf-8"))
        if json.dumps(old.get("results"), sort_keys=True) == new_results:
            print("Results unchanged - no PR needed.")
            sys.exit(0)
    except Exception:
        pass

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote {len(results)} autopsies to {out}")

def run(cmd):
    print("$ " + " ".join(cmd)); subprocess.run(cmd, check=True)

run(["git", "config", "user.name", "hive-bot"])
run(["git", "config", "user.email", "hive-bot@users.noreply.github.com"])
run(["git", "checkout", "-B", "tco/refresh"])
run(["git", "add", "apps/web/public/data/autopsies.json"])
run(["git", "commit", "-m", "chore(data): refresh TCO autopsy results"])
run(["git", "push", "-u", "origin", "tco/refresh", "--force"])
r = subprocess.run(["gh", "pr", "create", "--title", "Refresh TCO autopsy results",
                    "--body", f"Variants: {len(results)} | BEV avg/mo: {summary['bev_avg_monthly_eur']} | non-BEV avg/mo: {summary['ice_avg_monthly_eur']}",
                    "--base", "main", "--head", "tco/refresh"])
if r.returncode != 0:
    print("PR already open - branch updated instead.")
