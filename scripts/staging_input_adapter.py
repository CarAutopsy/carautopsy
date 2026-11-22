"""Read-only adapter: flat pilot staging records -> identity-conflict input.

The original staging records are never modified. Each adapted record keeps the
source record verbatim under `raw`. No value is inferred, normalized into
existence, merged or promoted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

EXPECTED_STAGING_COUNT = 48


class AdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError("INVALID_INPUT") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def variant_id_from_filename(filename: str) -> str:
    """Stable rule: the JSON filename stem, with no case or whitespace changes."""
    name = Path(filename).name
    if name.endswith(".json"):
        name = name[:-5]
    if not name:
        raise AdapterError("EMPTY_VARIANT_ID")
    return name


def adapt_record(raw: dict[str, Any], filename: str) -> dict[str, Any]:
    """Map only existing fields; unknown values stay null. Raw record is preserved."""
    if not isinstance(raw, dict):
        raise AdapterError("INVALID_RECORD")
    source = dict(raw)  # verbatim copy of every supplied field

    def value(name: str) -> Any:
        return raw.get(name)

    variant = value("variant")
    identity = {
        "make": value("brand"),
        "model": value("model"),
        "variant": variant,
        "model_year": value("model_year"),
        "body_style": value("body_style"),
        "powertrain": value("powertrain"),
        "trim": variant,
        "drivetrain": value("drivetrain"),
    }
    specifications = {
        "battery_capacity_kwh": value("battery_capacity_usable_kwh"),
        "range": value("wltp_range_km"),
    }
    price = {
        "price_tier": value("price_tier"),
        "price_value": value("price_value"),
        "source_url": value("price_source_url"),
        "source_date": value("price_source_date"),
        "vat_basis": value("vat_basis"),
        "confidence": value("price_confidence"),
    }
    sources = []
    if value("source_id") is not None or value("source_url") is not None or value("source_date") is not None:
        sources.append({
            "source_id": value("source_id"),
            "url": value("source_url"),
            "retrieved": value("source_date"),
        })
    provenance = {"sources": sources}

    return {
        "variant_id": variant_id_from_filename(filename),
        "identity": identity,
        "specifications": specifications,
        "price": price,
        "provenance": provenance,
        "raw": source,
    }


def validate_adapted_batch(records: list[dict[str, Any]], *,
                           expected_count: int = EXPECTED_STAGING_COUNT) -> list[str]:
    errors: list[str] = []
    if len(records) != expected_count:
        errors.append(f"expected exactly {expected_count} staging records, got {len(records)}")
    ids = [r.get("variant_id") for r in records]
    if len(set(ids)) != len(ids):
        errors.append("duplicate derived variant_id")
    for record in records:
        label = record.get("variant_id") or "<unknown>"
        if not record.get("identity", {}).get("make"):
            errors.append(f"{label}: missing brand")
        if not record.get("identity", {}).get("model"):
            errors.append(f"{label}: missing model")
        raw = record.get("raw")
        if not isinstance(raw, dict):
            errors.append(f"{label}: raw record missing")
        else:
            expected_brand = raw.get("brand")
            if record.get("identity", {}).get("make") != expected_brand:
                errors.append(f"{label}: raw brand not preserved")
            if record.get("identity", {}).get("model") != raw.get("model"):
                errors.append(f"{label}: raw model not preserved")
    return errors


def generate(input_dir: Path, *, expected_count: int = EXPECTED_STAGING_COUNT) -> dict[str, Any]:
    if not input_dir.is_dir():
        raise AdapterError("INVALID_INPUT_DIR")
    files = sorted(input_dir.glob("*.json"))
    if len(files) != expected_count:
        raise AdapterError("COUNT_MISMATCH")
    records: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    for path in files:
        raw = _read_json(path)
        records.append(adapt_record(raw, path.name))
        inputs.append({"path": str(path), "sha256": _sha256(path), "read_only": True})
    records.sort(key=lambda r: r["variant_id"])
    errors = validate_adapted_batch(records, expected_count=expected_count)
    if errors:
        raise AdapterError("VALIDATION_FAILED:" + " | ".join(errors[:5]))
    return {
        "schema_version": 1,
        "artifact": "staging-input-adapter",
        "deterministic": True,
        "input_files": inputs,
        "record_count": len(records),
        "variant_id_rule": "filename stem with .json removed; no case or whitespace changes",
        "records": records,
        "rejected_count": 0,
        "catalog_writes": 0,
        "staging_writes": 0,
        "provider_calls": 0,
        "source_records_modified": False,
    }


def tool_input(adapter_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Strip raw copies for the downstream conflict tool's input contract."""
    return [{k: v for k, v in record.items() if k != "raw"}
            for record in adapter_payload["records"]]


def safe_report_path(path: Path, root: Path = ROOT) -> Path:
    resolved = path.resolve()
    for prefix in ((root / "catalog").resolve(), (root / "catalog/variants").resolve(),
                   (root / "staging").resolve()):
        if resolved == prefix or prefix in resolved.parents:
            raise AdapterError("UNSAFE_REPORT_PATH")
    allowed = ((root / "docs/research").resolve(), (root / "docs/operations").resolve())
    if not any(resolved == base or base in resolved.parents for base in allowed):
        raise AdapterError("UNSAFE_REPORT_PATH")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--tool-input", type=Path)
    parser.add_argument("--expected-count", type=int, default=EXPECTED_STAGING_COUNT)
    parser.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = parser.parse_args(argv)
    if args.check and (args.report or args.tool_input):
        parser.error("--check must not be combined with output paths")
    try:
        payload = generate(args.input_dir, expected_count=args.expected_count)
        if args.report is not None:
            target = safe_report_path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                              encoding="utf-8")
        if args.tool_input is not None:
            target = safe_report_path(args.tool_input)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(tool_input(payload), indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    except AdapterError as exc:
        print(f"STAGING_ADAPTER_BLOCKED: {exc.code}", file=sys.stderr)
        return 3
    print(json.dumps({
        "record_count": payload["record_count"],
        "rejected_count": payload["rejected_count"],
        "catalog_writes": payload["catalog_writes"],
        "staging_writes": payload["staging_writes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
