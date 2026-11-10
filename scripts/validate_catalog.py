"""Validate the structural contract of every vehicle catalog JSON record."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "vehicle-variant.schema.json"
DEFAULT_CATALOG = ROOT / "catalog" / "variants"


def validate_catalog(
    catalog_dir: Path = DEFAULT_CATALOG,
    schema_path: Path = DEFAULT_SCHEMA,
) -> list[str]:
    """Return actionable validation errors; an empty list means success."""
    errors: list[str] = []

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        validator = Draft7Validator(schema)
    except (OSError, json.JSONDecodeError, ValueError, SchemaError) as exc:
        return [f"Schema error ({schema_path}): {exc}"]

    if not catalog_dir.is_dir():
        return [f"Catalog directory does not exist: {catalog_dir}"]

    files = sorted(catalog_dir.glob("*.json"))
    if not files:
        return [f"No vehicle JSON files found in {catalog_dir}"]

    seen_ids: dict[str, Path] = {}
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
            continue

        if not isinstance(record, dict):
            errors.append(f"{path}: record must be a JSON object")
            continue

        for error in sorted(validator.iter_errors(record), key=lambda item: list(map(str, item.path))):
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"{path}: {location}: {error.message}")

        variant_id = record.get("variant_id")
        if isinstance(variant_id, str) and variant_id:
            previous = seen_ids.get(variant_id)
            if previous is not None:
                errors.append(f"{path}: duplicate variant_id '{variant_id}' also used by {previous}")
            else:
                seen_ids[variant_id] = path

    return errors


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args(argv)

    errors = validate_catalog(args.catalog_dir, args.schema)
    if errors:
        print(f"Catalog validation failed with {len(errors)} error(s):", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    count = len(list(args.catalog_dir.glob("*.json")))
    print(f"Catalog validation passed: {count} vehicle record(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
