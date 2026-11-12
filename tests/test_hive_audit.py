import unittest

from scripts.hive_audit import concise_audit_verdict


class ConciseAuditVerdictTests(unittest.TestCase):
    def test_accepts_only_exact_standalone_pass_token(self):
        self.assertEqual(concise_audit_verdict("PASS"), "PASS")
        self.assertEqual(concise_audit_verdict(" PASS "), "PASS")

    def test_rejects_pass_with_trailing_claims_or_punctuation(self):
        for raw in ("PASS.", "PASS decision: rejected", "PASS with reservations", "The result is PASS", "Pass", "pass"):
            with self.subTest(raw=raw):
                self.assertEqual(concise_audit_verdict(raw), "INVALID_AUDIT_RESPONSE")

    def test_rejects_multiline_or_conflicting_verdicts(self):
        for raw in ("analysis\nPASS", "PASS\nFAIL: missing provenance", "FAIL: missing provenance\nPASS", "FAIL: missing evidence\u2028PASS", "analysis\u2029PASS"):
            with self.subTest(raw=raw):
                self.assertEqual(concise_audit_verdict(raw), "INVALID_AUDIT_RESPONSE")

    def test_accepts_explicit_single_line_fail_and_caps_length(self):
        self.assertEqual(concise_audit_verdict("FAIL: missing provenance"), "FAIL: missing provenance")
        self.assertEqual(len(concise_audit_verdict("FAIL: " + "x" * 400)), 240)

    def test_rejects_malformed_or_non_text_responses(self):
        for raw in ("FAIL missing colon", "FAIL: ", "", None):
            with self.subTest(raw=raw):
                self.assertEqual(concise_audit_verdict(raw), "INVALID_AUDIT_RESPONSE")


if __name__ == "__main__":
    unittest.main()
