import unittest

from scripts.hive_audit import concise_audit_verdict


class ConciseAuditVerdictTests(unittest.TestCase):
    def test_accepts_only_standalone_pass(self):
        self.assertEqual(concise_audit_verdict("PASS"), "PASS")
        self.assertEqual(concise_audit_verdict("analysis\nPASS\n"), "PASS")
        self.assertEqual(concise_audit_verdict("Pass."), "PASS")

    def test_rejects_pass_with_trailing_claims(self):
        for raw in ("PASS decision: rejected", "PASS with reservations", "The result is PASS"):
            with self.subTest(raw=raw):
                self.assertEqual(concise_audit_verdict(raw), "INVALID_AUDIT_RESPONSE")

    def test_rejects_conflicting_verdicts_in_either_order(self):
        self.assertEqual(concise_audit_verdict("PASS\nFAIL: missing provenance"), "INVALID_AUDIT_RESPONSE")
        self.assertEqual(concise_audit_verdict("FAIL: missing provenance\nPASS"), "INVALID_AUDIT_RESPONSE")

    def test_accepts_explicit_fail_and_caps_length(self):
        self.assertEqual(concise_audit_verdict("FAIL: missing provenance"), "FAIL: missing provenance")
        self.assertEqual(len(concise_audit_verdict("FAIL: " + "x" * 400)), 240)

    def test_rejects_malformed_or_non_text_responses(self):
        for raw in ("FAIL missing colon", "", None):
            with self.subTest(raw=raw):
                self.assertEqual(concise_audit_verdict(raw), "INVALID_AUDIT_RESPONSE")


if __name__ == "__main__":
    unittest.main()
