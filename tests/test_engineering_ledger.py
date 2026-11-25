"""Offline tests for the namespaced engineering outcome ledger (issue #114)."""
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from engineering_ledger import (  # noqa: E402
    ALLOWED_CODES,
    LEDGER_NAMESPACE,
    MAX_ENGINEERING_ATTEMPTS,
    EngineeringLedgerError,
    empty_ledger,
    is_exhausted,
    load_safe_ledger,
    namespaced_key,
    record_engineering_outcome,
)
from engineering_task import validate_task_contract  # noqa: E402
from hive_outcomes import (  # noqa: E402
    AUDIT_SUCCESS,
    MANUAL_REVIEW_REQUIRED,
    PROVIDER_TRANSPORT_FAILURE,
    PROVENANCE_REJECTION,
    RESPONSE_FORMAT_FAILURE,
    VEHICLE_QUALITY_REJECTION,
)


BASE = {
    "task_id": "eng-ledger-001",
    "repository": "CarAutopsy/carautopsy",
    "base_sha": "a" * 40,
    "allowed_paths": ["tests/fixtures/example.json"],
    "goal": "Bounded ledger improvement",
    "acceptance_criteria": ["tests pass"],
    "max_patch_bytes": 1000,
    "max_files_touched": 2,
    "timeout_seconds": 60,
    "max_provider_calls": 2,
    "max_spend_units": 0,
    "requires_owner_approval": True,
}
DIGEST = "d" * 64


def real_verification_artifact(contract):
    """Produce a genuine artifact from engineering_verification.run_verification."""
    from engineering_verification import _Completed, run_verification, snapshot_manifest

    target = contract["allowed_paths"][0]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"ok": true}\n', encoding="utf-8")
        manifest = snapshot_manifest(root, contract["allowed_paths"])
        return run_verification(
            contract,
            manifest,
            "f" * 64,
            root=root,
            check_names=("repo_audit",),
            runner=lambda argv, **kwargs: _Completed(0, b"17 passed\n", b""),
            status_probe=lambda _root: "",
        )


def fixture():
    contract = validate_task_contract(BASE)
    reservation = {
        "reservation_id": "r" * 24,
        "task_id": contract["task_id"],
        "base_sha": contract["base_sha"],
        "status": "reserved",
        "requires_owner_approval": True,
    }
    bundle = {"bundle_sha256": DIGEST}
    return contract, reservation, bundle, empty_ledger()


class EngineeringLedgerTests(unittest.TestCase):
    def setUp(self):
        self.contract, self.reservation, self.bundle, self.ledger = fixture()

    def test_namespace_isolation_and_input_non_mutation(self):
        key = namespaced_key("eng-ledger-001")
        self.assertEqual(key, "engineering:eng-ledger-001")
        before = copy.deepcopy(self.ledger)
        ledger, entry, retryable = record_engineering_outcome(
            self.ledger, self.contract, self.reservation, self.bundle,
            PROVIDER_TRANSPORT_FAILURE,
        )
        self.assertEqual(self.ledger, before)
        self.assertEqual(list(ledger["entries"]), [key])
        self.assertEqual(ledger["schema_version"], 1)
        self.assertEqual(ledger["namespace"], LEDGER_NAMESPACE)
        self.assertTrue(retryable)
        self.assertIs(entry["execution_enabled"], False)
        self.assertIs(entry["publication_enabled"], False)
        self.assertTrue(entry["requires_owner_approval"])

        foreign = {"schema_version": 1, "namespace": LEDGER_NAMESPACE,
                   "entries": {"variant_id.bev.model-x": {}}}
        with self.assertRaises(EngineeringLedgerError):
            load_safe_ledger(foreign)

    def test_hive_or_legacy_entries_are_rejected(self):
        for key in ("eng-ledger-001", "hive:eng-ledger-001", "variant_id.x", "engineering:other"):
            with self.subTest(key=key):
                bad = {"schema_version": 1, "namespace": LEDGER_NAMESPACE, "entries": {key: {}}}
                with self.assertRaises(EngineeringLedgerError):
                    load_safe_ledger(bad)

        _, entry, _ = record_engineering_outcome(
            self.ledger, self.contract, self.reservation, self.bundle,
            PROVIDER_TRANSPORT_FAILURE,
        )
        polluted = empty_ledger()
        polluted["entries"][namespaced_key("eng-ledger-001")] = dict(entry, variant_id="real-car")
        with self.assertRaisesRegex(EngineeringLedgerError, "Hive/legacy"):
            load_safe_ledger(polluted)

    def test_idempotent_replay_does_not_double_count(self):
        first, first_entry, first_retryable = record_engineering_outcome(
            self.ledger, self.contract, self.reservation, self.bundle,
            PROVIDER_TRANSPORT_FAILURE,
        )
        second, second_entry, second_retryable = record_engineering_outcome(
            first, self.contract, self.reservation, self.bundle,
            PROVIDER_TRANSPORT_FAILURE,
        )
        self.assertEqual(first, second)
        self.assertEqual(first_entry, second_entry)
        self.assertEqual(first_retryable, second_retryable)
        self.assertEqual(second_entry["counters"]["provider_attempts"], 1)

    def test_retry_ceiling_exhaustion_is_fail_closed(self):
        ledger, entry, retryable = record_engineering_outcome(
            self.ledger, self.contract, self.reservation, self.bundle,
            PROVIDER_TRANSPORT_FAILURE,
        )
        for expected in (2, 3):
            # A real retry produces a fresh evidence digest; identical replays
            # are intentionally idempotent and must not increment counters.
            fresh_bundle = {"bundle_sha256": format(expected, "064x")}
            ledger, entry, retryable = record_engineering_outcome(
                ledger, self.contract, self.reservation, fresh_bundle,
                PROVIDER_TRANSPORT_FAILURE,
            )
            self.assertEqual(entry["counters"]["provider_attempts"], expected)
        self.assertFalse(retryable)
        self.assertTrue(is_exhausted(entry))
        self.assertEqual(entry["counters"]["provider_attempts"], MAX_ENGINEERING_ATTEMPTS)

    def test_counter_classification_and_terminal_codes(self):
        ledger, entry, retryable = record_engineering_outcome(
            self.ledger, self.contract, self.reservation, self.bundle,
            RESPONSE_FORMAT_FAILURE,
        )
        self.assertEqual(entry["counters"]["format_attempts"], 1)
        self.assertEqual(entry["counters"]["provider_attempts"], 0)
        self.assertTrue(retryable)

        other_bundle = {"bundle_sha256": "e" * 64}
        for code in (PROVENANCE_REJECTION, VEHICLE_QUALITY_REJECTION):
            _, entry, _ = record_engineering_outcome(
                empty_ledger(), self.contract, self.reservation, other_bundle, code
            )
            self.assertEqual(entry["counters"]["verification_attempts"], 1)

        for terminal in (AUDIT_SUCCESS, MANUAL_REVIEW_REQUIRED):
            _, entry, retryable = record_engineering_outcome(
                empty_ledger(), self.contract, self.reservation, other_bundle, terminal
            )
            self.assertFalse(retryable)
            self.assertEqual(is_exhausted(entry), terminal == MANUAL_REVIEW_REQUIRED)

    def test_allowlisted_codes_only(self):
        self.assertEqual(len(ALLOWED_CODES), 6)
        for code in ("verification_failure", "audit_success ", "", None, 123, "PASS"):
            with self.subTest(code=code):
                with self.assertRaises(EngineeringLedgerError):
                    record_engineering_outcome(
                        self.ledger, self.contract, self.reservation, self.bundle, code
                    )

    def test_malformed_inputs_fail_closed(self):
        for bad_contract in (dict(self.contract, task_id="not-safe"), dict(self.contract, base_sha="x")):
            with self.subTest(contract=bad_contract.get("task_id", "bad-sha")):
                with self.assertRaises(EngineeringLedgerError):
                    record_engineering_outcome(
                        self.ledger, bad_contract, self.reservation, self.bundle,
                        PROVIDER_TRANSPORT_FAILURE,
                    )
        with self.assertRaises(EngineeringLedgerError):
            record_engineering_outcome(
                self.ledger, self.contract, dict(self.reservation, reservation_id=""),
                self.bundle, PROVIDER_TRANSPORT_FAILURE,
            )
        with self.assertRaises(EngineeringLedgerError):
            record_engineering_outcome(
                self.ledger, self.contract, self.reservation, {"bundle_sha256": "not-a-digest"},
                PROVIDER_TRANSPORT_FAILURE,
            )
        with self.assertRaises(EngineeringLedgerError):
            load_safe_ledger({"schema_version": 99, "namespace": LEDGER_NAMESPACE, "entries": {}})

    def test_digest_variants_are_accepted_and_consistency_enforced(self):
        for bundle in ({"evidence_digest": DIGEST}, {"snapshot_digest": DIGEST}):
            with self.subTest(bundle=bundle):
                _, entry, _ = record_engineering_outcome(
                    self.ledger, self.contract, self.reservation, bundle,
                    PROVIDER_TRANSPORT_FAILURE,
                )
                self.assertEqual(entry["digest"], DIGEST)
        # Priority: bundle_sha256 wins for bundles, even if another digest is present.
        _, entry, _ = record_engineering_outcome(
            self.ledger, self.contract, self.reservation,
            {"bundle_sha256": DIGEST, "evidence_digest": "e" * 64},
            PROVIDER_TRANSPORT_FAILURE,
        )
        self.assertEqual(entry["digest"], DIGEST)
        # A present but malformed authoritative field fails closed (no fallback).
        with self.assertRaises(EngineeringLedgerError):
            record_engineering_outcome(
                self.ledger, self.contract, self.reservation,
                {"bundle_sha256": "not-a-digest", "evidence_digest": DIGEST},
                PROVIDER_TRANSPORT_FAILURE,
            )


    def test_real_run_verification_artifact_is_accepted(self):
        artifact = real_verification_artifact(self.contract)
        self.assertIn("snapshot_digest", artifact)
        self.assertIn("evidence_digest", artifact)
        self.assertNotEqual(artifact["snapshot_digest"], artifact["evidence_digest"])
        ledger, entry, retryable = record_engineering_outcome(
            self.ledger, self.contract, self.reservation, artifact,
            PROVIDER_TRANSPORT_FAILURE,
        )
        # evidence_digest is authoritative for real artifacts.
        self.assertEqual(entry["digest"], artifact["evidence_digest"])
        self.assertTrue(retryable)
        self.assertEqual(ledger["namespace"], LEDGER_NAMESPACE)

    def test_terminal_and_exhausted_entries_are_sticky(self):
        for terminal in (AUDIT_SUCCESS, MANUAL_REVIEW_REQUIRED):
            ledger, _entry, _ = record_engineering_outcome(
                self.ledger, self.contract, self.reservation, self.bundle, terminal
            )
            with self.assertRaisesRegex(EngineeringLedgerError, "terminal engineering outcome is sticky"):
                record_engineering_outcome(
                    ledger, self.contract, self.reservation,
                    {"bundle_sha256": "e" * 64}, PROVIDER_TRANSPORT_FAILURE,
                )

        ledger = empty_ledger()
        for attempt in range(MAX_ENGINEERING_ATTEMPTS):
            bundle = {"bundle_sha256": format(attempt + 1, "064x")}
            ledger, entry, retryable = record_engineering_outcome(
                ledger, self.contract, self.reservation, bundle, VEHICLE_QUALITY_REJECTION
            )
        self.assertFalse(retryable)
        self.assertTrue(is_exhausted(entry))
        with self.assertRaisesRegex(EngineeringLedgerError, "exhausted engineering outcome is sticky"):
            record_engineering_outcome(
                ledger, self.contract, self.reservation,
                {"bundle_sha256": "f" * 64}, VEHICLE_QUALITY_REJECTION,
            )

    def test_provider_faults_do_not_consume_revision_allowance(self):
        ledger = empty_ledger()
        for attempt in range(MAX_ENGINEERING_ATTEMPTS):
            bundle = {"bundle_sha256": format(attempt + 1, "064x")}
            ledger, entry, retryable = record_engineering_outcome(
                ledger, self.contract, self.reservation, bundle, PROVIDER_TRANSPORT_FAILURE
            )
            self.assertEqual(entry["counters"]["attempts"], 0)
            self.assertEqual(entry["counters"]["provider_attempts"], attempt + 1)
        # Provider retry budget is exhausted but the code-revision allowance is intact.
        self.assertFalse(retryable)
        self.assertEqual(entry["counters"]["verification_attempts"], 0)

    def test_seen_attempt_history_is_bounded_and_idempotent(self):
        from engineering_ledger import MAX_SEEN_ATTEMPT_IDS

        first_bundle = {"bundle_sha256": "1" * 64}
        ledger, first_entry, _ = record_engineering_outcome(
            self.ledger, self.contract, self.reservation, first_bundle,
            VEHICLE_QUALITY_REJECTION,
        )
        self.assertEqual(first_entry["seen_attempt_ids"], [first_entry["attempt_id"]])

        before = copy.deepcopy(ledger)
        replayed, replay_entry, _ = record_engineering_outcome(
            ledger, self.contract, self.reservation, first_bundle,
            VEHICLE_QUALITY_REJECTION,
        )
        self.assertEqual(replayed, before)
        self.assertEqual(replay_entry, first_entry)

        second_bundle = {"bundle_sha256": "2" * 64}
        ledger, second_entry, _ = record_engineering_outcome(
            ledger, self.contract, self.reservation, second_bundle,
            VEHICLE_QUALITY_REJECTION,
        )
        self.assertEqual(
            second_entry["seen_attempt_ids"],
            [first_entry["attempt_id"], second_entry["attempt_id"]],
        )
        self.assertLessEqual(len(second_entry["seen_attempt_ids"]), MAX_SEEN_ATTEMPT_IDS)

        # The stored history itself is bounded and validated on load.
        oversized = copy.deepcopy(second_entry)
        oversized["seen_attempt_ids"] = [format(i, "064x") for i in range(MAX_SEEN_ATTEMPT_IDS + 1)]
        oversized["attempt_id"] = oversized["seen_attempt_ids"][-1]
        bad_ledger = empty_ledger()
        bad_ledger["entries"][namespaced_key(self.contract["task_id"])] = oversized
        with self.assertRaises(EngineeringLedgerError):
            load_safe_ledger(bad_ledger)


class LedgerPurityTests(unittest.TestCase):
    def test_module_has_no_network_or_write_capabilities(self):
        source = (ROOT / "scripts" / "engineering_ledger.py").read_text(encoding="utf-8")
        for forbidden in ("subprocess", "requests", "urllib", "os.environ", "gh ", "git "):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_no_production_script_imports_the_ledger(self):
        imports = []
        for path in (ROOT / "scripts").glob("*.py"):
            if path.name == "engineering_ledger.py":
                continue
            if "engineering_ledger" in path.read_text(encoding="utf-8"):
                imports.append(path.name)
        self.assertEqual(imports, [])

    def test_record_is_deterministic_and_pure(self):
        contract = validate_task_contract(BASE)
        reservation = {
            "reservation_id": "r" * 24,
            "task_id": contract["task_id"],
            "base_sha": contract["base_sha"],
        }
        source = empty_ledger()
        before = copy.deepcopy(source)
        first = record_engineering_outcome(
            source, contract, reservation, {"bundle_sha256": DIGEST},
            PROVIDER_TRANSPORT_FAILURE,
        )
        second = record_engineering_outcome(
            source, contract, reservation, {"bundle_sha256": DIGEST},
            PROVIDER_TRANSPORT_FAILURE,
        )
        self.assertEqual(first, second)
        self.assertEqual(source, before)
        self.assertEqual(first[1]["attempt_id"], second[1]["attempt_id"])
        self.assertEqual(first[1]["seen_attempt_ids"], second[1]["seen_attempt_ids"])


if __name__ == "__main__":
    unittest.main()
