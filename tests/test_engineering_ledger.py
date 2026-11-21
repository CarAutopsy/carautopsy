"""Offline tests for the namespaced engineering outcome ledger (issue #114)."""
import copy
import hashlib
import sys
import unittest
from pathlib import Path


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
        with self.assertRaises(EngineeringLedgerError):
            record_engineering_outcome(
                self.ledger, self.contract, self.reservation,
                {"bundle_sha256": DIGEST, "evidence_digest": "e" * 64},
                PROVIDER_TRANSPORT_FAILURE,
            )


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

    def test_determinism_of_ids(self):
        self.assertEqual(
            hashlib.sha256(b"r" * 24 + b":" + DIGEST.encode() + b":" + PROVIDER_TRANSPORT_FAILURE.encode()).hexdigest(),
            hashlib.sha256(f"{'r' * 24}:{DIGEST}:{PROVIDER_TRANSPORT_FAILURE}".encode()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
