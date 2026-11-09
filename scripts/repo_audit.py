#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "repo_audit.md"

required = [
    "README.md",
    "docs/README.md",
    "docs/protocols/vehicle-catalog-protocol-v104.md",
    "docs/protocols/article-writing-protocol-v104.md",
    "docs/protocols/session-handover-protocol-v101.md",
    "schemas/vehicle-variant.schema.json",
    "catalog/variants",
    "country-packs/AT/manifest.yaml",
    "data-connectors/agent_config.yaml",
]

warnings = []
errors = []
passed = []

def check_path(rel):
    p = ROOT / rel
    if p.exists():
        passed.append(f"PASS: {rel}")
    else:
        warnings.append(f"MISSING: {rel}")

def walk_keys(obj, path="root"):
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k != k.strip():
                found.append(f"{path}.{k!r}")
            found.extend(walk_keys(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(walk_keys(v, f"{path}[{i}]"))
    return found

for item in required:
    check_path(item)

web_pkg = ROOT / "apps" / "web" / "package.json"
if not web_pkg.exists():
    warnings.append("MISSING: apps/web/package.json — web app not yet committed or scaffold incomplete")
else:
    passed.append("PASS: apps/web/package.json")

for jf in sorted((ROOT / "catalog" / "variants").glob("*.json")):
    try:
        data = json.loads(jf.read_text(encoding="utf-8"))
        bad_keys = walk_keys(data)
        if bad_keys:
            errors.append(f"JSON key whitespace in {jf.relative_to(ROOT)}: {bad_keys[:5]}")
        else:
            passed.append(f"PASS JSON: {jf.relative_to(ROOT)}")
    except Exception as exc:
        errors.append(f"Invalid JSON {jf.relative_to(ROOT)}: {exc}")

schema = ROOT / "schemas" / "vehicle-variant.schema.json"
if schema.exists():
    try:
        json.loads(schema.read_text(encoding="utf-8"))
        passed.append("PASS JSON: schemas/vehicle-variant.schema.json")
    except Exception as exc:
        errors.append(f"Invalid schema JSON: {exc}")

REPORT.parent.mkdir(parents=True, exist_ok=True)

lines = [
    "# CarAutopsy Repository Audit",
    "",
    f"Generated: {datetime.now(timezone.utc).isoformat()}",
    "",
    "## Summary",
    "",
    f"- Passed: {len(passed)}",
    f"- Warnings: {len(warnings)}",
    f"- Errors: {len(errors)}",
    "",
    "## Errors",
    "",
]
lines += [f"- {x}" for x in errors] or ["None."]
lines += ["", "## Warnings", ""]
lines += [f"- {x}" for x in warnings] or ["None."]
lines += ["", "## Passed", ""]
lines += [f"- {x}" for x in passed] or ["None."]
lines += [
    "",
    "## Interpretation",
    "",
    "Warnings do not necessarily mean the repository is broken. They identify incomplete areas.",
    "Errors should be fixed before relying on the affected component.",
]

REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(REPORT.read_text(encoding="utf-8"))

if errors:
    raise SystemExit(1)
