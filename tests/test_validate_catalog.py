import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_catalog import validate_catalog


VALID_RECORD = {
    "schema_version": "1.0.0",
    "variant_id": "test.make.model",
    "status": "current",
    "identity": {"make": "Test"},
    "provenance": {"confidence": "low"},
}


class CatalogValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.catalog = self.root / "catalog"
        self.catalog.mkdir()
        self.schema = self.root / "schema.json"
        self.schema.write_text(
            json.dumps({
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "required": ["schema_version", "variant_id", "status", "identity", "provenance"],
                "properties": {
                    "schema_version": {"type": "string"},
                    "variant_id": {"type": "string"},
                    "status": {"type": "string"},
                    "identity": {"type": "object", "required": ["make"],
                                 "properties": {"make": {"type": "string"}}},
                    "provenance": {"type": "object", "required": ["confidence"],
                                   "properties": {"confidence": {"enum": ["low", "medium", "high", "official"]}}},
                },
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_record(self, name, record):
        (self.catalog / name).write_text(json.dumps(record), encoding="utf-8")

    def test_accepts_valid_sparse_record(self):
        self.write_record("valid.json", VALID_RECORD)
        self.assertEqual(validate_catalog(self.catalog, self.schema), [])

    def test_reports_missing_required_fields_and_wrong_types(self):
        self.write_record("invalid.json", {"variant_id": 42, "identity": [], "provenance": {}})
        errors = validate_catalog(self.catalog, self.schema)
        self.assertTrue(any("schema_version" in error for error in errors))
        self.assertTrue(any("variant_id" in error for error in errors))
        self.assertTrue(any("identity" in error for error in errors))

    def test_reports_invalid_json_with_filename(self):
        (self.catalog / "broken.json").write_text("{not-json", encoding="utf-8")
        errors = validate_catalog(self.catalog, self.schema)
        self.assertTrue(any("broken.json" in error and "invalid JSON" in error for error in errors))

    def test_reports_duplicate_variant_ids(self):
        self.write_record("one.json", VALID_RECORD)
        self.write_record("two.json", VALID_RECORD)
        errors = validate_catalog(self.catalog, self.schema)
        self.assertTrue(any("duplicate variant_id" in error for error in errors))

    def test_reports_empty_catalog(self):
        errors = validate_catalog(self.catalog, self.schema)
        self.assertTrue(any("No vehicle JSON files found" in error for error in errors))

    def test_reports_invalid_schema(self):
        self.schema.write_text('{"type": "not-a-json-schema-type"}', encoding="utf-8")
        self.write_record("valid.json", VALID_RECORD)
        errors = validate_catalog(self.catalog, self.schema)
        self.assertTrue(any("Schema error" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
