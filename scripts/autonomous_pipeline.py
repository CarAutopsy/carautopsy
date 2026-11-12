import json, math, os, re, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
import yaml, requests
from provider_retry import generate_content_with_fallback
from hive_batch import bounded_batch_size, next_unattempted_task
from hive_pr import fetch_all_open_pull_requests, select_open_research_pr
from hive_state import load_state, reconcile_with_pr, save_state, proposal_state_base
from hive_research_gate import ResearchPaused, require_verified_retrieval
from hive_orchestration import OrchestrationRejected, run_hive_research_and_audit
from hive_source_policy import SourcePolicyDenied, load_policy, require_variant_coverage
from hive_outcomes import AUDIT_SUCCESS, MANUAL_REVIEW_REQUIRED, classify_audit_results, classify_defect_category, record_outcome, requires_manual_review, migrate_legacy_entry, exhausted_outcome

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
    """Return content plus a safe failure class; never expose provider error bodies."""
    if not key:
        return None, "provider_transport_failure"
    try:
        content, used_model = call_provider(prompt, key, url, model)
        if content and used_model != model:
            print(f"   [Gemini fallback model: {used_model}]")
        return content, None
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        print(f"   [provider response format failed: {type(exc).__name__}]")
        return None, "response_format_failure"
    except requests.exceptions.RequestException as exc:
        print(f"   [provider request failed: {type(exc).__name__}]")
        return None, "provider_transport_failure"
    except Exception as exc:
        print(f"   [provider request failed: {type(exc).__name__}]")
        return None, "provider_transport_failure"

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
    """Return content or a deterministic provider/format failure class."""
    excluded = set(exclude_vendors or [])
    failures = []
    for name, vendor, key, url, model in PROVIDERS:
        if not key or vendor in excluded:
            continue
        out, failure = call_llm(prompt, key, url, model)
        if out:
            print(f"   [provider: {name}]")
            return out, name, vendor, None
        failures.append(failure)
    failure_code = "response_format_failure" if "response_format_failure" in failures else "provider_transport_failure"
    return None, None, None, failure_code

def call_vendor(prompt, vendor):
    """Try every configured endpoint for one vendor before classifying its failure."""
    failures = []
    matched = False
    for name, provider_vendor, key, url, model in PROVIDERS:
        if provider_vendor != vendor:
            continue
        matched = True
        if not key:
            failures.append("provider_transport_failure")
            continue
        out, failure = call_llm(prompt, key, url, model)
        if out:
            print(f"   [audit provider: {name}]")
            return out, name, None
        failures.append(failure)
    if not matched:
        return None, None, "provider_transport_failure"
    failure_code = "response_format_failure" if "response_format_failure" in failures else "provider_transport_failure"
    return None, None, failure_code

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

# Runtime orchestration is wired but remains deliberately unreachable until
# issue #37 acceptance, issue #47 independent review, and explicit owner approval.
# Smoke tests and the full TCO route intentionally bypass this research-only gate.
VERIFIED_RETRIEVAL_AVAILABLE = False
# A single research PR may contain a small batch; never let one run fan out.
RESEARCH_BATCH_SIZE = bounded_batch_size(os.getenv("HIVE_RESEARCH_BATCH_SIZE"), default=3, maximum=5)
HIVE_SOURCE_POLICY = None
if RESEARCH_ONLY:
    try:
        require_verified_retrieval(VERIFIED_RETRIEVAL_AVAILABLE)
        HIVE_SOURCE_POLICY = load_policy()
        if not HIVE_SOURCE_POLICY.get("source_policies"):
            raise SourcePolicyDenied("owner-approved source policy entries are empty")
        queue_path = ROOT / "tasks" / "queue.json"
        queued_tasks = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
        upcoming_ids = [
            item.get("variant_id") for item in queued_tasks[:RESEARCH_BATCH_SIZE]
            if isinstance(item, dict)
        ]
        require_variant_coverage(HIVE_SOURCE_POLICY, upcoming_ids)
    except (ResearchPaused, SourcePolicyDenied) as exc:
        print(f"HIVE_RESEARCH_PAUSED: {exc}", file=sys.stderr)
        sys.exit(2)

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
research_failures_this_run = 0
MAX_AUDIT_ATTEMPTS = 3
MAX_RESEARCH_ATTEMPTS = 3
MAX_VERDICT_CHARS = 240
def curate_one(attempted_variant_ids=None):
    """Research and independently audit at most one not-yet-attempted batch variant."""
    global audit_failures_this_run, research_failures_this_run
    qp = ROOT / "tasks" / "queue.json"
    if not qp.exists(): return False, "no queue"
    tasks = json.loads(qp.read_text())
    if not tasks: return False, "queue empty"
    
    attempted_variant_ids = attempted_variant_ids if attempted_variant_ids is not None else set()
    skipped = 0
    while tasks:
        task = next_unattempted_task(tasks, attempted_variant_ids)
        if task is None:
            qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
            return False, f"all remaining queued variants already attempted in this batch (skipped {skipped} existing)"
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
        prior_entry, _ = migrate_legacy_entry(prior_entry)
        if prior_entry and not requires_manual_review(prior_entry) and exhausted_outcome(prior_entry):
            tasks = [item for item in tasks if item.get("variant_id") != vid]
            qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
            return True, f"retry ceiling already exhausted for {vid}; retained for human review"
        if prior_entry and requires_manual_review(prior_entry):
            entry, _ = record_outcome(task, prior_entry, MANUAL_REVIEW_REQUIRED, stage="legacy_reconciliation")
            failed = [item for item in failed if (item.get("task") or {}).get("variant_id") != vid]
            failed.append(entry)
            fp.write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
            tasks = [item for item in tasks if item.get("variant_id") != vid]
            qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
            return True, f"legacy retry state for {vid} quarantined for human review"

        prior_categories = (prior_entry or {}).get("defect_categories") or []
        research_context = {"previous_audit_categories": prior_categories}
        attempted_variant_ids.add(vid)

        schema = json.loads((ROOT / "schemas" / "vehicle-variant.schema.json").read_text(encoding="utf-8"))
        try:
            orchestration, audit_results = run_hive_research_and_audit(
                reserved_task=task,
                schema=schema,
                config=HIVE_SOURCE_POLICY,
                researcher=call_any,
                auditor=call_vendor,
                research_context=research_context,
            )
        except OrchestrationRejected as exc:
            if exc.code == "retrieval_unavailable":
                raise ResearchPaused(
                    f"approved evidence is unavailable for reserved variant {vid}; "
                    "no researcher/auditor call or durable state mutation was performed"
                ) from exc
            research_code = exc.code if exc.code in {
                "provider_transport_failure", "response_format_failure", "provenance_rejection"
            } else "response_format_failure"
            if research_code in {"provider_transport_failure", "response_format_failure"}:
                research_failures_this_run += 1
            stage = "candidate_validation" if research_code == "provenance_rejection" else "research"
            provider_status = "OFFLINE" if research_code == "provider_transport_failure" else "INVALID"
            entry, retryable = record_outcome(
                task,
                prior_entry,
                research_code,
                stage=stage,
                provider_statuses=[{"provider": "researcher", "status": provider_status}],
            )
            counters = entry["outcome"]["counters"]
            entry.update({
                "attempts": counters["attempts"], "max_attempts": MAX_AUDIT_ATTEMPTS,
                "research_attempts": counters["research_attempts"],
                "max_research_attempts": MAX_RESEARCH_ATTEMPTS,
                "provider_attempts": counters["provider_attempts"],
                "format_attempts": counters["format_attempts"],
                "provenance_attempts": counters["provenance_attempts"],
            })
            failed = [item for item in failed
                      if (item.get("task") or {}).get("variant_id") != vid]
            failed.append(entry)
            fp.write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
            if retryable:
                tasks = tasks[1:] + [task]
                outcome = f"{research_code} for {vid}; retry queued"
            else:
                tasks = [item for item in tasks if item.get("variant_id") != vid]
                outcome = f"{research_code} retry ceiling reached; retained for human review"
            qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
            return True, f"{outcome} (skipped {skipped} existing)"

        veh = orchestration.candidate
        res_name = orchestration.researcher_provider or "unknown"
        extensions = veh.setdefault("extensions", {})
        if not isinstance(extensions, dict):
            extensions = {}
            veh["extensions"] = extensions
        extensions["hive"] = {
            "researcher": res_name,
            "curated_utc": datetime.now(timezone.utc).isoformat(),
        }
        for item in audit_results:
            print(f"Auditor {item.get('provider', item.get('vendor', 'unknown'))} says: {item.get('verdict', 'INVALID_AUDIT_RESPONSE')}")
        
        audit_code = classify_audit_results(audit_results)
        safe_audits = []
        for item in audit_results:
            verdict = str(item.get("verdict", "")).strip()
            status = "PASS" if verdict.upper() == "PASS" else (
                "OFFLINE" if verdict.upper() == "OFFLINE" else (
                    "INVALID" if verdict.upper() == "INVALID_AUDIT_RESPONSE" else "FAIL"
                )
            )
            safe_audits.append({
                "provider": str(item.get("provider", "auditor"))[:40],
                "vendor": str(item.get("vendor", "unknown"))[:40],
                "verdict": status,
            })
        veh["extensions"]["hive"]["audits"] = safe_audits
        # Only deterministic outcome codes and safe provider statuses enter the ledger.
        if audit_code != AUDIT_SUCCESS:
            if audit_code == "vehicle_quality_rejection":
                audit_failures_this_run += 1
            fp = ROOT / "tasks" / "failed.json"
            failed = json.loads(fp.read_text()) if fp.exists() else []
            entry, retryable = record_outcome(
                task, prior_entry, audit_code, stage="audit",
                provider_statuses=[
                    {"provider": item["provider"], "status": item["verdict"]}
                    for item in safe_audits
                ],
                defect_categories=[
                    classify_defect_category(item.get("verdict", ""))
                    for item in audit_results
                    if str(item.get("verdict", "")).upper().startswith("FAIL:")
                ],
            )
            counters = entry["outcome"]["counters"]
            entry.update({
                "attempts": counters["attempts"], "max_attempts": MAX_AUDIT_ATTEMPTS,
                "research_attempts": counters["research_attempts"],
                "max_research_attempts": MAX_RESEARCH_ATTEMPTS,
                "provider_attempts": counters["provider_attempts"],
                "format_attempts": counters["format_attempts"],
                "provenance_attempts": counters["provenance_attempts"],
                "audits": safe_audits, "candidate": veh,
            })
            failed = [item for item in failed if (item.get("task") or {}).get("variant_id") != vid]
            failed.append(entry)
            fp.write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8")
            if retryable:
                tasks = tasks[1:] + [task]
                outcome = f"{audit_code} for {vid}; retry queued"
            else:
                tasks = [item for item in tasks if item.get("variant_id") != vid]
                outcome = f"{audit_code} retry ceiling reached; retained for human review"
            qp.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
            return True, f"{outcome} (skipped {skipped} existing)"
        
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

def get_open_research_pr():
    """Return the sole open Hive PR, if any; fail closed on ambiguous state."""
    def fetch_page(limit):
        """Fetch a bounded page of open PR metadata from the GitHub CLI."""
        raw = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--base", "main",
             "--limit", str(limit), "--json", "number,headRefName,headRepository"],
            capture_output=True, text=True, check=True,
        ).stdout
        return json.loads(raw)

    pull_requests = fetch_all_open_pull_requests(fetch_page)
    return select_open_research_pr(pull_requests, "CarAutopsy/carautopsy")


# Reuse the pending proposal branch instead of stopping the scheduler.
# This carries queue/failed-ledger state forward between 15-minute runs and
# accumulates candidate work in one human-review PR without creating duplicates.
open_research_pr = get_open_research_pr() if RESEARCH_ONLY else None
if open_research_pr:
    # Start from the pending proposal's queue/ledger snapshot, not stale main.
    run(["git", "fetch", "origin", open_research_pr["headRefName"]])
    run(["git", "checkout", "-B", open_research_pr["headRefName"],
         f"origin/{open_research_pr['headRefName']}"])
    # The PR branch carries the ledger while a proposal is open. Align it with
    # hive/state first: adopt a hand-edited state, or resync a mirror that lagged.
    reconcile_with_pr(ROOT)
elif RESEARCH_ONLY:
    # No pending proposal: resume from the ledger saved on the hive/state branch.
    load_state(ROOT)

batch_messages = []
attempted_variant_ids = set()
try:
    for _ in range(RESEARCH_BATCH_SIZE if RESEARCH_ONLY else 1):
        queue_path = ROOT / "tasks" / "queue.json"
        queued = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
        if not queued:
            break
        did_work, batch_msg = curate_one(attempted_variant_ids if RESEARCH_ONLY else None)
        if not did_work:
            break
        batch_messages.append(batch_msg)
except ResearchPaused as exc:
    print(f"HIVE_RESEARCH_PAUSED: {exc}", file=sys.stderr)
    sys.exit(exc.exit_code)

curated = bool(batch_messages)
msg = "; ".join(batch_messages) if batch_messages else "queue empty"
print(f"Research batch: {len(batch_messages)}/{RESEARCH_BATCH_SIZE if RESEARCH_ONLY else 1} item(s)")
for batch_msg in batch_messages:
    print(f"Curation: {batch_msg}")

if RESEARCH_ONLY:
    # Inspect only paths staged below; unrelated files must not cause empty commits.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--",
         "catalog/variants", "tasks/queue.json", "tasks/failed.json"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not dirty:
        print("Research-only run made no changes.")
        if audit_failures_this_run or research_failures_this_run:
            sys.exit(1)
        sys.exit(0)
    catalog_dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "catalog/variants"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not open_research_pr and not catalog_dirty:
        # Nothing for a reviewer: keep the retry counters on hive/state
        # instead of opening a proposal PR that holds only ledger changes.
        saved = save_state(ROOT, f"chore(hive-state): {msg}")
        print("No catalog candidates and no pending proposal; ledger " + ("saved to hive/state." if saved else "unchanged."))
        sys.exit(0)
    run(["git", "config", "user.name", "hive-bot"])
    run(["git", "config", "user.email", "hive-bot@users.noreply.github.com"])
    if open_research_pr:
        branch = open_research_pr["headRefName"]
    else:
        branch = "hive/research-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run(["git", "checkout", "-b", branch])
    run(["git", "add", "catalog/variants", "tasks/queue.json", "tasks/failed.json"])
    substantive = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--",
         "catalog/variants", "tasks/failed.json"],
        check=False,
    )
    if substantive.returncode == 0 and not open_research_pr:
        print("Queue-only research change; skipping PR to avoid reordering-only proposals.")
        sys.exit(0)
    if substantive.returncode not in (0, 1):
        raise RuntimeError("Could not determine whether research produced substantive changes.")
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        check=False,
    )
    if staged.returncode == 0:
        print("No proposal changes to publish.")
        sys.exit(0)
    if staged.returncode != 1:
        raise RuntimeError("Could not determine whether staged research changes exist.")
    state_base = proposal_state_base(ROOT)
    run(["git", "commit", "-m", f"chore(hive): {msg}", "-m",
         f"Hive-State-Base: {state_base or 'none'}"])
    run(["git", "push", "-u", "origin", branch])
    if open_research_pr:
        print(f"Updated existing Hive research PR #{open_research_pr['number']}; awaiting human review.")
    else:
        run(["gh", "pr", "create", "--title", f"Hive research: {msg}",
             "--body", "Automated vehicle research proposal. Two independent AI vendors must explicitly approve each record. All AI-generated data remains low-confidence and requires human review before acceptance.",
             "--base", "main", "--head", branch])
        print("Research proposal pushed; awaiting human review.")
    # Mirror the ledger so hive/state never lags the PR branch.
    save_state(ROOT, f"chore(hive-state): {msg}", proposal_head=subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip())
    if audit_failures_this_run or research_failures_this_run:
        print(
            f"Research cycle completed and saved for human review: "
            f"{audit_failures_this_run} audit rejection(s), "
            f"{research_failures_this_run} research failure(s)."
        )
    else:
        print("Research cycle completed successfully; proposal is awaiting human review.")
    # A rejected candidate is a data-quality outcome, not a failed scheduler
    # execution. Rejections remain explicit in tasks/failed.json and the PR.
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
