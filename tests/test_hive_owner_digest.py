"""Tests for the read-only Hive owner digest."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hive_owner_digest as digest
import hive_outcomes


class HiveOwnerDigestTests(unittest.TestCase):
    def test_summary_counts_versioned_outcomes_and_preserves_queue_order(self):
        retryable, _ = hive_outcomes.record_outcome(
            {"variant_id": "skoda.enyaq", "make": "Skoda", "model": "Enyaq"},
            None,
            hive_outcomes.PROVIDER_TRANSPORT_FAILURE,
            stage="research",
            now="2026-11-18T05:00:00Z",
        )
        exhausted = None
        for _ in range(3):
            exhausted, _ = hive_outcomes.record_outcome(
                {"variant_id": "bmw.ix3", "make": "BMW", "model": "iX3"},
                exhausted,
                hive_outcomes.VEHICLE_QUALITY_REJECTION,
                stage="audit",
                now="2026-11-18T05:01:00Z",
            )

        report = digest.build_digest(
            [
                {"variant_id": "kia.ev6", "make": "Kia", "model": "EV6"},
                {"variant_id": "tesla.model-y", "make": "Tesla", "model": "Model Y"},
            ],
            [retryable, exhausted],
            generated_at="2026-11-18T05:02:00Z",
        )
        self.assertEqual(report["summary"]["queued"], 2)
        self.assertEqual(report["summary"]["failed_records"], 2)
        self.assertEqual(report["summary"]["retryable"], 1)
        self.assertEqual(report["summary"]["exhausted"], 1)
        self.assertEqual(report["summary"]["manual_review_required"], 0)
        self.assertEqual(report["queue"][0]["variant_id"], "kia.ev6")
        self.assertEqual(
            report["summary"]["outcomes_by_code"],
            {
                hive_outcomes.PROVIDER_TRANSPORT_FAILURE: 1,
                hive_outcomes.VEHICLE_QUALITY_REJECTION: 1,
            },
        )

    def test_legacy_and_malformed_records_are_quarantined_without_raw_text(self):
        legacy = {
            "task": {"variant_id": "legacy.vehicle", "make": "Legacy", "model": "Vehicle"},
            "verdict": "INDEPENDENT_AUDIT_FAILED",
            "audits": [{"verdict": "FAIL: private raw auditor response"}],
        }
        report = digest.build_digest(
            [{"variant_id": "valid.vehicle"} , {"make": "missing-id"}],
            [legacy, {"task": {"make": "missing-id"}}],
            generated_at="2026-11-18T05:02:00Z",
        )
        self.assertEqual(report["summary"]["manual_review_required"], 2)
        self.assertEqual(report["summary"]["malformed_queue_records"], 1)
        self.assertEqual(report["summary"]["malformed_failed_records"], 1)
        self.assertEqual(report["summary"]["failed_records"], 2)
        self.assertNotIn("private raw auditor response", json.dumps(report))
        self.assertIn("manual_review_required", json.dumps(report))

    def test_unknown_outcome_is_manual_review_not_retryable(self):
        record = {
            "task": {"variant_id": "unknown.vehicle"},
            "outcome": {
                "schema_version": 1,
                "code": "future_unknown",
                "retryable": True,
                "counters": {},
            },
        }
        report = digest.build_digest([], [record], generated_at="2026-11-18T05:02:00Z")
        item = report["failed"][0]
        self.assertEqual(item["outcome_code"], hive_outcomes.MANUAL_REVIEW_REQUIRED)
        self.assertTrue(item["manual_review_required"])
        self.assertFalse(item["retryable"])
        self.assertTrue(item["exhausted"])

    def test_markdown_reports_read_only_boundary_and_safe_metadata(self):
        record, _ = hive_outcomes.record_outcome(
            {"variant_id": "a.vehicle", "make": "A", "model": "Vehicle"},
            None,
            hive_outcomes.PROVENANCE_REJECTION,
            stage="audit",
            defect_categories=["provenance_evidence"],
            now="2026-11-18T05:00:00Z",
        )
        report = digest.build_digest(
            [{"variant_id": "<script>alert(1)</script>", "make": "B", "model": "Vehicle"}],
            [record],
            generated_at="2026-11-18T05:02:00Z",
        )
        rendered = digest.render_markdown(report)
        self.assertIn("read-only; no fetch, reconciliation, dispatch, or provider calls", rendered)
        self.assertIn("provenance_rejection", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>", rendered)

    def test_invalid_json_constants_and_oversized_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            path.write_text("[NaN]", encoding="utf-8")
            with self.assertRaises(digest.OwnerDigestError):
                digest._read_array(path)
            path.write_bytes(b" " * (digest.MAX_INPUT_BYTES + 1))
            with self.assertRaises(digest.OwnerDigestError):
                digest._read_array(path)
            path.write_text("[" + ("9" * 4301) + "]", encoding="utf-8")
            with self.assertRaises(digest.OwnerDigestError):
                digest._read_array(path)

    def test_markdown_link_syntax_in_queue_labels_is_escaped(self):
        report = digest.build_digest(
            [{
                "variant_id": "safe.vehicle",
                "make": "[click](https://attacker.example)",
                "model": "Model",
            }],
            [],
            generated_at="2026-11-18T05:02:00Z",
        )
        rendered = digest.render_markdown(report)
        self.assertIn(r"\\[click\\]\\(https://attacker\\.example\\)", rendered)
        self.assertNotIn("[click](https://attacker.example)", rendered)

    def test_quarantined_outcome_does_not_expose_counters_or_timestamp(self):
        record = {
            "task": {"variant_id": "unknown.vehicle"},
            "at": "private prose should not be a timestamp",
            "outcome": {
                "schema_version": 1,
                "code": "unknown_code",
                "attempt_id": "x",
                "stage": "audit",
                "retryable": True,
                "at": "arbitrary untrusted prose",
                "provider_statuses": [],
                "counters": {
                    "provider_attempts": 999,
                    "format_attempts": 999,
                    "provenance_attempts": 999,
                    "attempts": 999,
                    "research_attempts": 999,
                },
            },
        }
        report = digest.build_digest([], [record], generated_at="2026-11-18T05:02:00Z")
        item = report["failed"][0]
        self.assertEqual(item["counters"], {})
        self.assertIsNone(item["at"])
        self.assertFalse(item["retryable"])
        self.assertTrue(item["manual_review_required"])

    def test_recognized_legacy_record_uses_read_only_migration_decision(self):
        legacy = {
            "task": {"variant_id": "legacy.vehicle", "make": "Legacy", "model": "Vehicle"},
            "verdict": "INDEPENDENT_AUDIT_FAILED",
            "attempts": 1,
            "research_attempts": 0,
            "audits": [
                {"provider": "deepseek", "vendor": "deepseek", "verdict": "FAIL: incorrect value"},
                {"provider": "gemini", "vendor": "google", "verdict": "FAIL: incorrect value"},
            ],
            "at": "2026-11-18T05:00:00Z",
        }
        report = digest.build_digest([], [legacy], generated_at="2026-11-18T05:02:00Z")
        item = report["failed"][0]
        self.assertTrue(item["legacy_migrated"])
        self.assertFalse(item["manual_review_required"])
        self.assertTrue(item["retryable"])
        self.assertFalse(item["exhausted"])
        self.assertEqual(item["outcome_code"], hive_outcomes.VEHICLE_QUALITY_REJECTION)

    def test_top_level_state_attempt_limit_overrides_retryable_outcome(self):
        record, _ = hive_outcomes.record_outcome(
            {"variant_id": "limited.vehicle"},
            None,
            hive_outcomes.VEHICLE_QUALITY_REJECTION,
            stage="audit",
            now="2026-11-18T05:00:00Z",
        )
        record["attempts"] = 3
        record["max_attempts"] = 3
        report = digest.build_digest([], [record], generated_at="2026-11-18T05:02:00Z")
        item = report["failed"][0]
        self.assertFalse(item["retryable"])
        self.assertTrue(item["exhausted"])

    def test_timezone_is_required_for_generated_timestamp(self):
        with self.assertRaises(digest.OwnerDigestError):
            digest.build_digest([], [], generated_at="2026-11-18T05:02:00")


if __name__ == "__main__":
    unittest.main()
