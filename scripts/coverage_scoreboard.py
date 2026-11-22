"""Generate a pilot coverage scoreboard from committed research candidate data.

The generator performs no network access, writes no catalog or staging records,
and treats registration weights as a provisional proxy unless an owner-approved
weight table is supplied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import price_tier

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS = ROOT / "docs/research/registration-weights-v1.json"
CORRECTION_TIERS = frozenset({
    "approximate", "approximate_cross_market", "range", "unavailable",
})
TCO_READY_TIERS = frozenset({"verified", "derived"})


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_candidates(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, dict):
        payload = payload.get("candidates")
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("candidate file must be a JSON array of objects")
    return payload


def load_weights(path: Path) -> dict[str, float]:
    payload = _load_json(path)
    weights = payload.get("weights", payload) if isinstance(payload, dict) else {}
    if not isinstance(weights, dict):
        raise ValueError("weight file must contain a weights object")
    clean: dict[str, float] = {}
    for key, value in weights.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            clean[str(key)] = float(value)
    return clean


def generate(candidates: list[dict[str, Any]], weights: dict[str, float], *,
             candidate_sha256: str | None = None, weights_sha256: str | None = None,
             weights_status: str = "owner_supplied",
             generated_at: str | None = None) -> dict[str, Any]:
    by_tier = {tier: 0 for tier in price_tier.PRICE_TIERS}
    for record in candidates:
        tier = record.get("price_tier")
        if tier in by_tier:
            by_tier[tier] += 1

    total = len(candidates)
    usable = [r for r in candidates if price_tier.usable_price(r)]
    price_quality = round(len(usable) / total, 6) if total else None

    weighted_total = sum(weights.get(str(r.get("model")), 0.0) for r in candidates)
    weighted_covered = sum(weights.get(str(r.get("model")), 0.0) for r in usable)
    registration_weighted = (
        round(weighted_covered / weighted_total, 6) if weighted_total > 0 else None
    )

    return {
        "schema_version": 1,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "candidate_sha256": candidate_sha256,
        "weights_sha256": weights_sha256,
        "weights_status": weights_status,
        "total_models": total,
        "models_by_price_tier": by_tier,
        "verified_count": by_tier["verified"],
        "derived_count": by_tier["derived"],
        "approximate_count": by_tier["approximate"],
        "approximate_cross_market_count": by_tier["approximate_cross_market"],
        "range_count": by_tier["range"],
        "unavailable_count": by_tier["unavailable"],
        "registration_weighted_coverage": registration_weighted,
        "registration_weight_base": weighted_total,
        "price_quality_coverage": price_quality,
        "correction_queue_count": sum(1 for r in candidates if r.get("price_tier") in CORRECTION_TIERS),
        "tco_ready_count": sum(1 for r in candidates if r.get("price_tier") in TCO_READY_TIERS),
        "coverage_gaps": [str(r.get("model")) for r in candidates if r.get("price_tier") == "unavailable"],
        "notes": [
            "TCO-ready count includes verified and derived tiers only; other TCO gates are not evaluated here.",
            "Registration weights are a planning proxy until replaced by owner-approved registration data.",
            "No catalog or staging record is written by this generator.",
        ],
    }


def generate_from_files(candidates_path: Path, weights_path: Path = DEFAULT_WEIGHTS) -> dict[str, Any]:
    candidates = load_candidates(candidates_path)
    weights = load_weights(weights_path)
    return generate(
        candidates,
        weights,
        candidate_sha256=_sha256(candidates_path),
        weights_sha256=_sha256(weights_path),
        weights_status="provisional_priority_proxy",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = generate_from_files(args.candidates, args.weights)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "total_models": report["total_models"],
        "registration_weighted_coverage": report["registration_weighted_coverage"],
        "price_quality_coverage": report["price_quality_coverage"],
        "correction_queue_count": report["correction_queue_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
