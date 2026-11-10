import unittest

from scripts.hive_audit import concise_audit_verdict


class ConciseAuditVerdictTests(unittest.TestCase):
    def test_accepts_only_standalone_pass(self):
        self.assertEqual(concise_audit_verdict("PASS"), "PASS")
        self.assertEqual(concise_audit_verdict("analysis\nPASS\n"), "PASS")

    def test_rejects_pass_with_trailing_claims(self):
        self.assertEqual(concise_audit_verdict("PASS decision: rejected"), "INVALID_AUDIT_RESPONSE")
        self.assertEqual(concise_audit_verdict("PASS with reservations"), "INVALID_AUDIT_RESPONSE")
        self.assertEqual(concise_audit_verdict("The result is PASS"), "INVALID_AUDIT_RESPONSE")

    def test_accepts_explicit_fail_and_caps_length(self):
        self.assertEqual(concise_audit_verdict("FAIL: missing provenance"), "FAIL: missing provenance")
        self.assertEqual(len(concise_audit_verdict("FAIL: " + "x" * 400)), 240)

    def test_rejects_malformed_or_non_text_responses(self):
        self.assertEqual(concise_audit_verdict("FAIL missing colon"), "INVALID_AUDIT_RESPONSE")
        self.assertEqual(concise_audit_verdict(""), "INVALID_AUDIT_RESPONSE")
        self.assertEqual(concise_audit_verdict(None), "INVALID_AUDIT_RESPONSE")


if __name__ == "__main__":
    unittest.main()
