"""Tests for owner-controlled source terms and live robots.txt enforcement."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from scripts.hive_source_policy import USER_AGENT, SourcePolicyDenied, _robots_can_fetch, check_source_access, load_policy


HOST = "oem.example"
URL = "https://oem.example/specs/car.html"
ROBOTS = b"User-agent: CarAutopsy-Research-Bot\nDisallow: /private/\nAllow: /specs/\n"


def config(**overrides):
    entry = {
        "host": HOST,
        "automated_access_allowed": True,
        "terms_url": "https://oem.example/terms",
        "terms_reviewed_at": "2026-11-01",
        "terms_reviewed_by": "repository-owner",
        "terms_review_ref": "https://github.com/CarAutopsy/carautopsy/issues/37",
        "approved_urls": [{"url": URL, "variant_ids": ["synthetic.model-x"]}],
    }
    value = {"version": 1, "approved_hosts": [HOST], "source_policies": [entry]}
    value.update(overrides)
    return value


class SourcePolicyTests(unittest.TestCase):
    def test_exact_approved_host_and_robots_allow(self):
        fetcher = Mock(return_value=SimpleNamespace(outcome="retrieved_unverified", body=ROBOTS))
        self.assertTrue(check_source_access(URL, config=config(), fetcher=fetcher, today=date(2026, 11, 11)))
        fetcher.assert_called_once()
        args, kwargs = fetcher.call_args
        self.assertEqual(args[0], "https://oem.example/robots.txt")
        self.assertEqual(kwargs["approved_hosts"], [HOST])

    def test_robots_disallow_denies_exact_target(self):
        body = b"User-agent: *\nDisallow: /specs/\n"
        fetcher = Mock(return_value=SimpleNamespace(outcome="retrieved_unverified", body=body))
        with self.assertRaisesRegex(SourcePolicyDenied, "disallows"):
            check_source_access(URL, config=config(), fetcher=fetcher, today=date(2026, 11, 11))

    def test_missing_or_rejected_robots_denies(self):
        for result in (
            SimpleNamespace(outcome="rejected", body=None),
            SimpleNamespace(outcome="retrieved_unverified", body=None),
        ):
            with self.subTest(result=result):
                with self.assertRaisesRegex(SourcePolicyDenied, "robots.txt could not"):
                    check_source_access(URL, config=config(), fetcher=Mock(return_value=result), today=date(2026, 11, 11))

    def test_malformed_robots_denies(self):
        fetcher = Mock(return_value=SimpleNamespace(outcome="retrieved_unverified", body=b"not a robots file"))
        with self.assertRaisesRegex(SourcePolicyDenied, "malformed directive"):
            check_source_access(URL, config=config(), fetcher=fetcher, today=date(2026, 11, 11))

    def test_malformed_disallow_without_colon_denies(self):
        with self.assertRaisesRegex(SourcePolicyDenied, "malformed directive"):
            _robots_can_fetch("User-agent: *\\nDisallow\\n", USER_AGENT, URL)

    def test_robots_longest_match_disallow_overrides_allow_root(self):
        text = "User-agent: *\\nAllow: /\\nDisallow: /specs/\\n"
        self.assertFalse(_robots_can_fetch(text, USER_AGENT, URL))

    def test_robots_longest_match_allow_can_override_parent_disallow(self):
        text = "User-agent: *\\nDisallow: /specs/\\nAllow: /specs/public/\\n"
        self.assertTrue(_robots_can_fetch(text, USER_AGENT, "https://oem.example/specs/public/model.html"))

    def test_robots_supports_wildcard_and_terminal_anchor(self):
        text = "User-agent: *\\nDisallow: /*.pdf$\\n"
        self.assertFalse(_robots_can_fetch(text, USER_AGENT, "https://oem.example/specs/model.pdf"))
        self.assertTrue(_robots_can_fetch(text, USER_AGENT, "https://oem.example/specs/model.pdf?download=1"))

    def test_invalid_utf8_robots_denies(self):
        fetcher = Mock(return_value=SimpleNamespace(outcome="retrieved_unverified", body=b"User-agent: *\n\xff"))
        with self.assertRaisesRegex(SourcePolicyDenied, "valid UTF-8"):
            check_source_access(URL, config=config(), fetcher=fetcher, today=date(2026, 11, 11))

    def test_fetch_exception_denies(self):
        with self.assertRaises(RuntimeError):
            check_source_access(URL, config=config(), fetcher=Mock(side_effect=RuntimeError("network")) , today=date(2026, 11, 11))

    def test_terms_must_be_explicitly_permitted(self):
        value = config()
        value["source_policies"][0]["automated_access_allowed"] = False
        with self.assertRaisesRegex(SourcePolicyDenied, "do not permit"):
            check_source_access(URL, config=value, fetcher=Mock(), today=date(2026, 11, 11))

    def test_terms_approval_requires_reviewer_and_review_reference(self):
        for key in ("terms_reviewed_by", "terms_review_ref"):
            value = config()
            value["source_policies"][0].pop(key)
            with self.subTest(key=key):
                with self.assertRaises(SourcePolicyDenied):
                    check_source_access(URL, config=value, fetcher=Mock(), today=date(2026, 11, 11))

    def test_terms_and_review_references_require_safe_https_urls(self):
        for key, value in (("terms_url", "http://oem.example/terms"), ("terms_review_ref", "https://user@oem.example/review")):
            policy = config()
            policy["source_policies"][0][key] = value
            with self.subTest(key=key):
                with self.assertRaises(SourcePolicyDenied):
                    check_source_access(URL, config=policy, fetcher=Mock(), today=date(2026, 11, 11))

    def test_terms_review_must_be_recent_and_valid(self):
        for reviewed in ("2025-01-01", "2026-12-01", "not-a-date"):
            with self.subTest(reviewed=reviewed):
                value = config()
                value["source_policies"][0]["terms_reviewed_at"] = reviewed
                with self.assertRaises(SourcePolicyDenied):
                    check_source_access(URL, config=value, fetcher=Mock(), today=date(2026, 11, 11))

    def test_missing_duplicate_or_unapproved_host_policy_denies(self):
        cases = [
            config(source_policies=[]),
            config(source_policies=[config()["source_policies"][0]] * 2),
            config(approved_hosts=[]),
        ]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(SourcePolicyDenied):
                    check_source_access(URL, config=value, fetcher=Mock(), today=date(2026, 11, 11))

    def test_unlisted_url_on_approved_host_is_denied(self):
        with self.assertRaisesRegex(SourcePolicyDenied, "exact URL list"):
            check_source_access("https://oem.example/other-model.html", config=config(), fetcher=Mock(), today=date(2026, 11, 11))

    def test_approved_source_requires_variant_scope(self):
        policy = config()
        policy["source_policies"][0]["approved_urls"][0]["variant_ids"] = []
        with self.assertRaisesRegex(SourcePolicyDenied, "variant IDs"):
            check_source_access(URL, config=policy, fetcher=Mock(), today=date(2026, 11, 11))

    def test_candidate_host_cannot_expand_allowlist(self):
        with self.assertRaises(SourcePolicyDenied):
            check_source_access("https://attacker.example/spec", config=config(), fetcher=Mock(), today=date(2026, 11, 11))

    def test_non_https_or_credentials_denied_before_fetch(self):
        fetcher = Mock()
        for url in ("http://oem.example/spec", "https://user@oem.example/spec"):
            with self.subTest(url=url):
                with self.assertRaises(SourcePolicyDenied):
                    check_source_access(url, config=config(), fetcher=fetcher, today=date(2026, 11, 11))
        fetcher.assert_not_called()

    def test_load_policy_fails_closed_on_missing_or_malformed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            with self.assertRaises(SourcePolicyDenied):
                load_policy(path)
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaises(SourcePolicyDenied):
                load_policy(path)

    def test_load_policy_requires_explicit_arrays_and_nonempty_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            for value in (
                {"version": 1, "approved_hosts": [], "source_policies": []},
                {"version": 2, "approved_hosts": [HOST], "source_policies": []},
                {"version": 1, "approved_hosts": [HOST], "source_policies": "bad"},
            ):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(value=value):
                    with self.assertRaises(SourcePolicyDenied):
                        load_policy(path)


if __name__ == "__main__":
    unittest.main()
