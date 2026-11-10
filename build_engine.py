"""Retired legacy engine builder; retained as a safe compatibility command."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
required = (ROOT / "scripts" / "tco_engine.py", ROOT / "engine" / "tco" / "calculator.py")
missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
if missing:
    print("Shared TCO engine files missing: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
print("Legacy engine builder retired; use scripts/tco_engine.py.")
print("No files changed; no git commands executed.")
