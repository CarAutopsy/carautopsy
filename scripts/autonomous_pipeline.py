import json, math, os, re, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
import yaml, requests
from provider_retry import post_gemini_with_retry

ROOT = Path.cwd()

def clean(o):
    if isinstance(o, dict):
        return {re.sub(r'[^a-zA-Z0-9_]', '', str(k)): clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(i) for i in o]
    if isinstance(o, str): return o.strip()
    return o

def load(p):
    with open(p, encoding="utf-8") as f:
        return clean(json.load(f) if p.suffix == ".json" else yaml.safe_load(f))

def clean_json_response(t):
    m = re.search(r"```json\s*(\{.*?\})\s*```", t, re.DOTALL)
    if m: return m.group(1)
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m: return m.group(0)
    return t

def call_llm(prompt, key, url, model):
    if not key: return None
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
                          timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None

# Provider fallback routing
QWEN_KEY = os.getenv("QWEN_API_KEY")
DEEP_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_CARAUTOPSY_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

PROVIDERS = [
    ("qwen-intl", "qwen", QWEN_KEY, "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
    ("qwen-cn", "qwen", QWEN_KEY, "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
    ("deepseek", "deepseek", DEEP_KEY, "https://api.deepseek.com/chat/completions", "deepseek-chat"),
    ("gemini", "google", GEMINI_KEY, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", GEMINI_MODEL),
]

def call_any(prompt, exclude_vendors=None):
    excluded = set(exclude_vendors or [])
    for name, vendor, key, url, model in PROVIDERS:
        if not key or vendor in excluded:
            continue
        out = call_llm(prompt, key, url, model)
        if out:
            print(f"   [provider: {name}]")
            return out, name, vendor
    return None, None, None

def call_vendor(prompt, vendor):
    for name, provider_vendor, key, url, model in PROVIDERS:
        if provider_vendor != vendor or not key:
            continue
        out = call_llm(prompt, key, url, model)
        if out:
            print(f"   [audit provider: {name}]")
            return out, name
    return None, None

def provider_smoke_test():
    """Exercise one endpoint per independent vendor without touching catalog or queue."""
    prompt = "Reply with exactly: CARAUTOPSY_PROVIDER_OK"
    checks = []
    # qwen-intl and qwen-cn share a vendor/key; test only one endpoint.
    smoke_providers = [
        ("qwen-intl", "qwen", QWEN_KEY, "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
        ("deepseek", "deepseek", DEEP_KEY, "https://api.deepseek.com/chat/completions", "deepseek-chat"),
        ("gemini", "google", GEMINI_KEY, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", GEMINI_MODEL),
    ]
    for name, vendor, key, url, model in smoke_providers:
        if not key:
            checks.append({"provider": name, "vendor": vendor, "model": model, "status": "MISSING_SECRET"})
            continue
        started = time.monotonic()
        try:
            request_kwargs = {
                "headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                "json": {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
            }
            # Retry Gemini on transient HTTP failures and network timeouts.
            # Qwen and DeepSeek retain their original single-attempt behavior.
            if vendor == "google":
                response = post_gemini_with_retry(url, **request_kwargs)
            else:
                response = requests.post(url, timeout=45, **request_kwargs)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty response content")
            checks.append({"provider": name, "vendor": vendor, "model": model, "status": "PASS",
                           "latency_ms": elapsed_ms, "response_chars": len(content.strip())})
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            # Do not print response bodies or credentials; expose only a short exception description.
            checks.append({"provider": name, "vendor": vendor, "model": model, "status": "FAIL",
                           "latency_ms": elapsed_ms, "error": type(exc).__name__ + ": " + str(exc)[:240]})
    print("PROVIDER_SMOKE_TEST=" + json.dumps(checks, ensure_ascii=False))
    failed = [item for item in checks if item["status"] != "PASS"]
    print(f"Provider smoke test: {len(checks) - len(failed)}/{len(checks)} passed.")
    return 1 if failed else 0

if "--provider-smoke-test" in sys.argv:
    import time
    sys.exit(provider_smoke_test())

taxes = load(ROOT / "country-packs/AT/taxes.yaml")
defaults = load(ROOT / "country-packs/AT/defaults.yaml")
FUEL = {"ice_diesel": 6.5, "ice_petrol": 6.0, "hev": 4.5, "phev": 5.0}
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

def analyze(v):
    identity = v.get("identity") or {}
    pt = identity.get("powertrain")
    if not pt: return None
    yrs = defaults.get("horizon_years_default", 5); km = defaults.get("annual_km_default", 15000)
    n = nova(v); mt = motor_monthly(v) * 12 * yrs
    if pt == "bev":
        ed = v.get("energy", {}).get("consumption_wh_km", {}) or {}
        wh = ed.get("real_world") or ed.get("wltp_combined") or 0
        energy = (wh / 1000.0) * km * defaults.get("energy", {}).get("electricity_tariff_eur_kwh", 0.35) * yrs
    else:
        l100 = ((v.get("extensions") or {}).get("fuel_consumption_l_100km") or {})
        l100 = l100.get("real_world") or FUEL.get(pt, 6.0)
        price = defaults.get("energy", {}).get("diesel_eur_l", 1.55) if pt == "ice_diesel" else defaults.get("energy", {}).get("petrol_eur_l", 1.65)
        energy = (l100 / 100.0) * km * price * yrs
    maint = MAINT.get(pt, 450) * yrs
    ins = defaults.get("insurance_proxy_annual_eur", {}).get("bev" if pt == "bev" else "ice", 1100) * yrs
    tyres = (km * yrs / defaults.get("tyres", {}).get("interval_km", 30000)) * defaults.get("tyres", {}).get("set_cost_eur", 800)
    insp = defaults.get("inspection_annual_proxy_eur", 35) * yrs
    total = n + mt + energy + maint + ins + tyres + insp
    offers = v.get("offers") or []
    return {
        "variant_id": v.get("variant_id"), "make": identity.get("make"), "model": identity.get("model"),
        "variant_name": identity.get("variant_name"), "powertrain": pt,
        "power_kw": round((v.get("performance", {}).get("power_w") or 0) / 1000.0, 1),
        "co2_gkm": v.get("emissions", {}).get("co2_wltp_gpkm"),
        "list_price_eur": round((offers[0].get("list_price_minor") or 0) / 100.0, 2) if offers else None,
        "nova_eur": n, "motor_tax_monthly_eur": motor_monthly(v),
        "energy_5y_eur": round(energy, 2), "maintenance_5y_eur": round(maint, 2),
        "insurance_5y_eur": round(ins, 2), "tyres_5y_eur": round(tyres, 2),
        "inspection_5y_eur": round(insp, 2), "total_5y_eur": round(total, 2),
        "monthly_eur": round(total / (yrs * 12), 2),
        "data_confidence": (v.get("provenance") or {}).get("confidence"),
    }

audit_failures_this_run = 0

def curate_one():
    global audit_failures_this_run
    qp = ROOT / "tasks" / "queue.json"
    if not qp.exists(): return False, "no queue"
    tasks = json.loads(qp.read_text())
    if not tasks: return False, "queue empty"
    
    skipped = 0
    while tasks:
        task = tasks[0]
        vid, make, model = task["variant_id"], task["make"], task["model"]
        existing = ROOT / "catalog" / "variants" / f"{vid}.json"
        
        # Skip if already valid
        if existing.exists():
            try:
                ev = load(existing)
                if (ev.get("identity") or {}).get("powertrain"):
                    skipped += 1
                    tasks = tasks[1:]
                    continue
            except Exception:
                pass  # malformed -> fall through and re-curate it
        
        print(f"Hive processing: {make} {model} ({vid})")
        rp = f"""You are the CarAutopsy Researcher agent.
Find OFFICIAL specifications for: {make} {model}.
Allowed sources only: OEM press kits, OEM configurators, EU type-approval/CoC data.
FORBIDDEN: EV Database, classifieds, forums.
Return ONLY a valid JSON object with exactly these top-level keys:
schema_version, variant_id, status, identity, performance, energy, dimensions, emissions, offers, warranty, extensions, provenance.
Rules: variant_id must be "{vid}". SI units: power in W (integer), battery in Wh (integer), mass in kg, price in minor units (cents) with currency EUR and country AT. Unknown = null, never 0.
provenance.sources must list the official URL(s) used, with retrieved date {datetime.now(timezone.utc).date().isoformat()}."""
        
        raw, res_name, res_vendor = call_any(rp)
        veh = None
        if raw:
            try:
                veh = json.loads(clean_json_response(raw))
                assert isinstance(veh, dict) and "identity" in veh
            except Exception as e:
                print(f"Researcher bad JSON: {e}"); veh = None
        
        if veh is None:
            tasks = tasks[1:] + [task]  # Requeue at end
            qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
            return True, f"research failed for {vid}, requeued; skipped {skipped} existing"
        
        veh["variant_id"] = vid
        veh.setdefault("schema_version", "1.0.0")
        veh.setdefault("status", "current")
        prov = veh.setdefault("provenance", {})
        prov["confidence"] = "low"
        prov["reviewed_by"] = None
        veh.setdefault("extensions", {})["hive"] = {
            "researcher": res_name or "unknown", 
            "curated_utc": datetime.now(timezone.utc).isoformat()
        }
        
        ap = f"""You are the CarAutopsy Auditor agent.
Review this vehicle JSON against Vehicle Catalog Protocol v1.04 and schema v1.0.0.
Reject (FAIL) if: hallucinated or inconsistent numbers, missing provenance URLs,
wrong units (e.g. kW stored in power_w), missing required keys, confidence above "low".
Data:
{json.dumps(veh, indent=2)}
Reply with exactly one line: PASS or FAIL: reason"""
        
        # Require independent vendor audits; Qwen's regional endpoints count as one vendor.
        audit_vendors = [vendor for vendor in ("deepseek", "google", "qwen") if vendor != res_vendor]
        audit_results = []
        for audit_vendor in audit_vendors:
            audit_raw, audit_name = call_vendor(ap, audit_vendor)
            audit_verdict = audit_raw.strip().splitlines()[0] if audit_raw else "OFFLINE"
            audit_results.append({"provider": audit_name or audit_vendor, "vendor": audit_vendor, "verdict": audit_verdict})
            print(f"Auditor {audit_name or audit_vendor} says: {audit_verdict}")

        veh["extensions"]["hive"]["audits"] = audit_results
        # Fail closed: every available independent vendor must explicitly PASS.
        passed = len(audit_results) >= 2 and all(item["verdict"].upper().startswith("PASS") for item in audit_results)
        if not passed:
            audit_failures_this_run += 1
            fp = ROOT / "tasks" / "failed.json"
            failed = json.loads(fp.read_text()) if fp.exists() else []
            failed.append({"task": task, "verdict": "INDEPENDENT_AUDIT_FAILED", "audits": audit_results, "at": datetime.now(timezone.utc).isoformat()})
            fp.write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
            tasks = tasks[1:]
            continue
        
        out = ROOT / "catalog" / "variants" / f"{vid}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(veh, indent=2) + "\n", encoding="utf-8")
        tasks = tasks[1:]
        qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
        return True, f"curated {vid} (skipped {skipped} existing)"
    
    qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    return (skipped > 0), f"queue exhausted; skipped {skipped} existing"

def run(cmd):
    print("$ " + " ".join(cmd)); subprocess.run(cmd, check=True)

curated, msg = curate_one()
print(f"Curation: {msg}")

results = []
for p in sorted((ROOT / "catalog" / "variants").glob("*.json")):
    try:
        r = analyze(load(p))
        if r: results.append(r)
    except Exception as e:
        print(f"skip {p.name}: {e}")

bevs = [r for r in results if r["powertrain"] == "bev"]
others = [r for r in results if r["powertrain"] != "bev"]
payload = {
    "results": results,
    "summary": {
        "variants": len(results),
        "bev_avg_monthly_eur": round(sum(r["monthly_eur"] for r in bevs) / len(bevs), 2) if bevs else None,
        "ice_avg_monthly_eur": round(sum(r["monthly_eur"] for r in others) / len(others), 2) if others else None,
    },
    "envelope": {
        "engine_version": "0.4.0", "country_pack": "AT@1.0.0",
        "assumptions_version": "AT-defaults@1.0.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(), "currency": "EUR",
        "horizon_years": defaults.get("horizon_years_default", 5),
        "annual_km": defaults.get("annual_km_default", 15000),
        "sources": ["AT-BMF-tax-2024", "AT-OEAMTC-57a", "AT-defaults-assumptions-1.0.0"],
        "note": "Operating + statutory costs only; excludes depreciation and financing.",
    },
}

out = ROOT / "apps" / "web" / "public" / "data" / "autopsies.json"
changed = True
if out.exists():
    try:
        old = json.loads(out.read_text(encoding="utf-8"))
        changed = json.dumps(old.get("results"), sort_keys=True) != json.dumps(results, sort_keys=True)
    except Exception:
        changed = True

if changed:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(results)} autopsies")

# Include queue/failed-ledger updates in the commit decision, not only catalog output.
if not subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip():
    print("No changes. Exiting.")
    if audit_failures_this_run:
        print(f"Pipeline rejected {audit_failures_this_run} vehicle record(s).")
        sys.exit(1)
    sys.exit(0)

run(["git", "config", "user.name", "hive-bot"])
run(["git", "config", "user.email", "hive-bot@users.noreply.github.com"])
run(["git", "add", "-A"])
run(["git", "commit", "-m", f"chore(autonomous): {msg} | {len(results)} autopsies"])
run(["git", "push", "origin", "main"])
print("Committed and pushed to main.")
if audit_failures_this_run:
    print(f"Pipeline rejected {audit_failures_this_run} vehicle record(s); marking workflow failed.")
    sys.exit(1)
