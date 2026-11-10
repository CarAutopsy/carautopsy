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

from tco_engine import calculate_tco, load_country_config

taxes, defaults, inspections = load_country_config(ROOT)
tco = lambda vehicle: calculate_tco(vehicle, taxes, defaults, inspections)

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
        "engine_version": "0.5.0",
        "country_pack": "AT@1.2.0-draft",
        "assumptions_version": "AT-defaults@1.0.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "currency": "EUR",
        "horizon_years": defaults.get("horizon_years_default", 5),
        "annual_km": defaults.get("annual_km_default", 15000),
        "sources": ["AT-BMF-tax-2025-2029", "AT-OEAMTC-57a", "AT-defaults-assumptions-1.0.0"],
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
