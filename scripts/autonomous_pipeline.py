import json, math, os, re, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
import yaml, requests
from provider_retry import generate_content_with_fallback

ROOT = Path.cwd()

def clean(o):
    """Recursively normalize keys and trim string values in decoded data."""
    if isinstance(o, dict):
        return {re.sub(r'[^a-zA-Z0-9_]', '', str(k)): clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(i) for i in o]
    if isinstance(o, str): return o.strip()
    return o

def load(p):
    """Load and normalize a JSON or YAML file from the repository."""
    with open(p, encoding="utf-8") as f:
        return clean(json.load(f) if p.suffix == ".json" else yaml.safe_load(f))

def clean_json_response(t):
    """Extract a JSON object from a provider response or fenced code block."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", t, re.DOTALL)
    if m: return m.group(1)
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m: return m.group(0)
    return t

def call_provider(prompt, key, url, model, temperature=0.1):
    """Return (text, actual_model), routing Gemini through its native API."""
    if not key:
        return None, model
    if "generativelanguage.googleapis.com" in url:
        return generate_content_with_fallback(
            prompt=prompt,
            api_key=key,
            primary_model=model,
            fallback_model=GEMINI_FALLBACK_MODEL,
            temperature=temperature,
        )
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature},
        timeout=120,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("provider returned empty response content")
    return content, model


def call_llm(prompt, key, url, model):
    """Call one model and treat provider errors as unavailable."""
    if not key:
        return None
    try:
        content, used_model = call_provider(prompt, key, url, model)
        if content and used_model != model:
            print(f"   [Gemini fallback model: {used_model}]")
        return content
    except Exception as exc:
        print(f"   [provider request failed: {type(exc).__name__}]")
        return None

# Provider fallback routing
QWEN_KEY = os.getenv("QWEN_API_KEY")
DEEP_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_CARAUTOPSY_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")

PROVIDERS = [
    ("qwen-intl", "qwen", QWEN_KEY, "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
    ("qwen-cn", "qwen", QWEN_KEY, "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
    ("deepseek", "deepseek", DEEP_KEY, "https://api.deepseek.com/chat/completions", "deepseek-chat"),
    ("gemini", "google", GEMINI_KEY, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", GEMINI_MODEL),
]

def call_any(prompt, exclude_vendors=None):
    """Return the first successful response from a non-excluded vendor."""
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
    """Call a specific independent vendor for an audit response."""
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
            content, used_model = call_provider(prompt, key, url, model, temperature=0)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty response content")
            checks.append({"provider": name, "vendor": vendor, "model": used_model, "status": "PASS",
                           "latency_ms": elapsed_ms, "response_chars": len(content.strip())})
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            # Do not print response bodies or credentials; expose only a short exception description.
            checks.append({"provider": name, "vendor": vendor, "model": model, "status": "FAIL",
                           "latency_ms": elapsed_ms, "error": type(exc).__name__ + ": " + str(exc)[:240]})
    print("PROVIDER_SMOKE_TEST=" + json.dumps(checks, ensure_ascii=False))
    failed = [item for item in checks if item["status"] != "PASS"]
    print(f"Provider smoke test: {len(checks) - len(failed)}/{len(checks)} passed.")
    # Gemini remains mandatory: the production audit requires two independent
    # vendors, so a smoke-test quorum would hide a real curation blocker.
    return 1 if failed else 0

if "--provider-smoke-test" in sys.argv:
    import time
    sys.exit(provider_smoke_test())

RESEARCH_ONLY = "--research-only" in sys.argv

if RESEARCH_ONLY:
    taxes = defaults = inspections = None
    analyze = None
else:
    from tco_engine import assert_tax_pack_publishable, calculate_tco, load_country_config
    taxes, defaults, inspections = load_country_config(ROOT)
    # TCO publication remains blocked until the statutory pack is verified.
    assert_tax_pack_publishable(taxes)
    analyze = lambda vehicle: calculate_tco(vehicle, taxes, defaults, inspections)

audit_failures_this_run = 0

def curate_one():
    """Research and independently audit at most one queued vehicle variant."""
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
        fp = ROOT / "tasks" / "failed.json"
        failed = json.loads(fp.read_text()) if fp.exists() else []
        prior_entry = next(
            (item for item in reversed(failed)
             if (item.get("task") or {}).get("variant_id") == vid),
            None,
        )
        prior_audits = (prior_entry or {}).get("audits") or []
        prior_failure = "; ".join(
            f"{audit.get('provider', audit.get('vendor', 'auditor'))}: "
            f"{audit.get('verdict', 'no verdict')}"
            for audit in prior_audits
            if isinstance(audit, dict)
        ) or ((prior_entry or {}).get("verdict") if prior_entry else "") or ""
        rp = f"""You are the CarAutopsy Researcher agent.
Find OFFICIAL specifications for: {make} {model}.
Allowed sources only: OEM press kits, OEM configurators, EU type-approval/CoC data.
FORBIDDEN: EV Database, classifieds, forums.
Return ONLY a valid JSON object with exactly these top-level keys:
schema_version, variant_id, status, identity, performance, energy, dimensions, emissions, offers, warranty, extensions, provenance.
Rules: variant_id must be "{vid}". SI units: power in W (integer), battery in Wh (integer), mass in kg, price in minor units (cents) with currency EUR and country AT. Unknown = null, never 0.
Every non-null technical claim must be supported by a directly relevant official provenance URL. Do not invent URLs, engine codes, trim details, or precision absent from the source. Resolve this previous audit finding explicitly: {prior_failure or "No previous finding"}.
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
            failed = [item for item in failed
                      if (item.get("task") or {}).get("variant_id") != vid]
            failed.append({"task": task, "verdict": "INDEPENDENT_AUDIT_FAILED", "audits": audit_results, "at": datetime.now(timezone.utc).isoformat()})
            fp.write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
            tasks = tasks[1:]
            continue
        
        out = ROOT / "catalog" / "variants" / f"{vid}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(veh, indent=2) + "\n", encoding="utf-8")
        # A successfully re-audited record clears its previous failed-ledger entry.
        failed = [item for item in failed
                  if (item.get("task") or {}).get("variant_id") != vid]
        fp.write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
        tasks = tasks[1:]
        qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
        return True, f"curated {vid} (skipped {skipped} existing)"
    
    qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    return (skipped > 0), f"queue exhausted; skipped {skipped} existing"

def run(cmd):
    """Run a checked subprocess command and print its invocation.""" 
    print("$ " + " ".join(cmd)); subprocess.run(cmd, check=True)

def has_open_research_pr():
    """Return whether a Hive research proposal is already awaiting review."""
    open_prs = subprocess.run(
        ["gh", "pr", "list", "--state", "open", "--base", "main",
         "--json", "headRefName", "--jq",
         '[.[] | select(.headRefName | startswith("hive/research-"))] | length'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return bool(open_prs and open_prs != "0")


# Check before provider calls so hourly runs do not spend API credits while
# an earlier research proposal is still awaiting human review.
if RESEARCH_ONLY and has_open_research_pr():
    print("An open Hive research PR already exists; skipping this run.")
    sys.exit(0)

curated, msg = curate_one()
print(f"Curation: {msg}")

if RESEARCH_ONLY:
    # Inspect only paths staged below; unrelated files must not cause empty commits.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--",
         "catalog/variants", "tasks/queue.json", "tasks/failed.json"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not dirty:
        print("Research-only run made no changes.")
        if audit_failures_this_run:
            sys.exit(1)
        sys.exit(0)
    run(["git", "config", "user.name", "hive-bot"])
    run(["git", "config", "user.email", "hive-bot@users.noreply.github.com"])
    branch = "hive/research-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run(["git", "checkout", "-b", branch])
    run(["git", "add", "catalog/variants", "tasks/queue.json", "tasks/failed.json"])
    substantive = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--",
         "catalog/variants", "tasks/failed.json"],
        check=False,
    )
    if substantive.returncode == 0:
        print("Queue-only research change; skipping PR to avoid reordering-only proposals.")
        if audit_failures_this_run:
            sys.exit(1)
        sys.exit(0)
    if substantive.returncode != 1:
        raise RuntimeError("Could not determine whether research produced substantive changes.")
    run(["git", "commit", "-m", f"chore(hive): {msg}"])
    run(["git", "push", "-u", "origin", branch])
    run(["gh", "pr", "create", "--title", f"Hive research: {msg}",
         "--body", "Automated vehicle research proposal. Two independent AI vendors must explicitly approve each record. All AI-generated data remains low-confidence and requires human review before acceptance.",
         "--base", "main", "--head", branch])
    print("Research proposal pushed; awaiting human review.")
    if audit_failures_this_run:
        sys.exit(1)
    sys.exit(0)

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
        "engine_version": "0.5.0", "country_pack": "AT@1.2.0-draft",
        "assumptions_version": "AT-defaults@1.0.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(), "currency": "EUR",
        "horizon_years": defaults.get("horizon_years_default", 5),
        "annual_km": defaults.get("annual_km_default", 15000),
        "sources": ["AT-BMF-tax-2025-2029", "AT-OEAMTC-57a", "AT-defaults-assumptions-1.0.0"],
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
