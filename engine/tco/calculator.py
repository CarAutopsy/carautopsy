"""Compatibility adapter for the retired legacy TCOEngine API."""
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tco_engine import calculate_tco, load_country_config


class TCOEngine:
    """Preserve the old call signature while delegating to the shared engine."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)

    def calculate(self, variant_id: str, country: str, annual_km: int, years: int) -> dict:
        if country != "AT":
            raise ValueError(f"Legacy TCO adapter supports only AT; got {country!r}")
        if annual_km <= 0 or years <= 0:
            raise ValueError("annual_km and years must be positive")
        taxes, defaults, inspections = load_country_config(self.repo_root)
        defaults = dict(defaults)
        defaults["annual_km_default"] = annual_km
        defaults["horizon_years_default"] = years
        with (self.repo_root / "catalog" / "variants" / f"{variant_id}.json").open(encoding="utf-8") as f:
            variant = json.load(f)
        # Draft packs are rejected by default; no legacy zero-tax fallback.
        result = calculate_tco(variant, taxes, defaults, inspections)
        result["engine_version"] = "0.5.0"
        result["country_pack"] = f"AT@{taxes.get('version', 'unknown')}"
        result["inputs"] = {"annual_km": annual_km, "years": years}
        result["outputs"] = {
            "nova_eur": result["nova_eur"],
            "monthly_motor_tax_eur": result["motor_tax_monthly_eur"],
            "total_operating_cost_eur": result["total_5y_eur"],
            "monthly_tco_eur": result["monthly_eur"],
        }
        return result
