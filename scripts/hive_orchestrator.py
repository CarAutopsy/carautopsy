import json, os, sys, subprocess, requests, re
from pathlib import Path
from datetime import datetime, timezone

REPO = Path.cwd()

def clean_json_response(text):
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m: return m.group(1)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m: return m.group(0)
    return text

def call_llm(prompt, api_key, url, model):
    if not api_key:
        print(f"   (no API key for {model} — skipping)")
        return None
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"⚠️ API call to {url} failed: {e}")
        return None

def run(cmd):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

queue_path = REPO / "tasks" / "queue.json"
if not queue_path.exists():
    print("No task queue found. Exiting.")
    sys.exit(0)
tasks = json.loads(queue_path.read_text())
if not tasks:
    print("Queue is empty. Nothing to do.")
    sys.exit(0)

task = tasks[0]
variant_id = task["variant_id"]; make = task["make"]; model = task["model"]
print(f"🐝 Hive Processing: {make} {model} ({variant_id})")

QWEN_KEY = os.getenv("QWEN_API_KEY")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_CARAUTOPSY_KEY")

research_prompt = f"""You are the CarAutopsy Researcher agent.
Find OFFICIAL specifications for: {make} {model}.
Allowed sources only: OEM press kits, OEM configurators, EU type-approval/CoC data.
FORBIDDEN: EV Database, classifieds, forums.
Return ONLY a valid JSON object with exactly these top-level keys:
schema_version, variant_id, status, identity, performance, energy, dimensions, emissions, offers, warranty, extensions, provenance.
Rules: variant_id must be "{variant_id}". SI units: power in W (integer), battery in Wh (integer), mass in kg, price in minor units (cents) with currency EUR and country AT. Unknown = null, never 0.
provenance.sources must list the official URL(s) used, with retrieved date {datetime.now(timezone.utc).date().isoformat()}.
"""
print("🧠 Calling Researcher (Qwen)...")
raw = call_llm(research_prompt, QWEN_KEY,
               "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus")
vehicle = None
if raw:
    try:
        vehicle = json.loads(clean_json_response(raw))
        assert isinstance(vehicle, dict) and "identity" in vehicle
    except Exception as e:
        print(f"❌ Researcher returned unusable JSON: {e}")
        vehicle = None
if vehicle is None:
    print("❌ Research failed. Task stays in queue for retry next hour.")
    sys.exit(0)

# Governance: AI drafts are ALWAYS low confidence until a human verifies
vehicle["variant_id"] = variant_id
vehicle.setdefault("schema_version", "1.0.0")
vehicle.setdefault("status", "current")
prov = vehicle.setdefault("provenance", {})
prov["confidence"] = "low"
prov["reviewed_by"] = None
vehicle.setdefault("extensions", {})["hive"] = {
    "researcher": "qwen", "auditor": "deepseek",
    "curated_utc": datetime.now(timezone.utc).isoformat()
}

audit_prompt = f"""You are the CarAutopsy Auditor agent.
Review this vehicle JSON against Vehicle Catalog Protocol v1.04 and schema v1.0.0.
Reject (FAIL) if: hallucinated or inconsistent numbers, missing provenance URLs,
wrong units (e.g. kW stored in power_w), missing required keys, confidence above "low".
Data:
{json.dumps(vehicle, indent=2)}
Reply with exactly one line: PASS or FAIL: reason
"""
print("🔍 Calling Auditor (DeepSeek)...")
audit_raw = call_llm(audit_prompt, DEEPSEEK_KEY,
                     "https://api.deepseek.com/chat/completions", "deepseek-chat")
audit_result = audit_raw.strip().splitlines()[0] if audit_raw else "OFFLINE: auditor unavailable — human review required"
print(f"Auditor says: {audit_result}")
if audit_result.upper().startswith("FAIL"):
    print("❌ Auditor rejected. Task stays in queue for retry next hour.")
    sys.exit(0)

print("✅ Audit passed. Opening PR...")
out_path = REPO / "catalog" / "variants" / f"{variant_id}.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(vehicle, indent=2) + "\n", encoding="utf-8")

queue_path.write_text(json.dumps(tasks[1:], indent=2) + "\n", encoding="utf-8")

branch = f"hive/{variant_id}"
run(["git", "config", "user.name", "hive-bot"])
run(["git", "config", "user.email", "hive-bot@users.noreply.github.com"])
run(["git", "checkout", "-B", branch])
run(["git", "add", str(out_path.relative_to(REPO)), "tasks/queue.json"])
run(["git", "commit", "-m", f"feat(catalog): add {make} {model} via Hive (researcher=qwen, auditor=deepseek)"])
run(["git", "push", "-u", "origin", branch])

pr_body = (f"Automated curation by The Hive.\n\n"
           f"- Researcher: Qwen\n- Auditor: DeepSeek\n- Audit verdict: `{audit_result}`\n"
           f"- Provenance confidence: low (AI draft — human verification required before upgrade)\n\n"
           f"```json\n{json.dumps(vehicle, indent=2)}\n```")
run(["gh", "pr", "create", "--title", f"🐝 Hive: {make} {model} ({variant_id})",
     "--body", pr_body, "--base", "main", "--head", branch])
print("🎉 PR opened. Awaiting human review.")
