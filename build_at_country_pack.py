"""Deprecated safe validator for the maintained Austria country pack.

The former generator embedded stale statutory rates, reset the manifest to
verified, overwrote maintained files, and pushed directly to main. It is
intentionally non-mutating now. Edit reviewed country-pack sources in Git.
"""
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parent
PACK = ROOT / "country-packs" / "AT"


def main():
    manifest = yaml.safe_load((PACK / "manifest.yaml").read_text(encoding="utf-8"))
    taxes = yaml.safe_load((PACK / "taxes.yaml").read_text(encoding="utf-8"))
    if manifest.get("status") != "draft" or taxes.get("status") != "draft":
        print("ERROR: Austria tax pack status mismatch or unexpectedly verified.")
        return 1
    if manifest.get("version") != taxes.get("version"):
        print("ERROR: Austria manifest/tax versions differ.")
        return 1
    if "annual_rules" not in (taxes.get("nova") or {}):
        print("ERROR: year-aware NoVA rules missing.")
        return 1
    motor = taxes.get("motorbezogene_versicherungssteuer") or {}
    if "bev_m1" not in motor or "annual_rules" not in motor:
        print("ERROR: year-aware motor-tax rules missing.")
        return 1
    print("Austria pack validated. No files changed; generator is non-mutating.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
