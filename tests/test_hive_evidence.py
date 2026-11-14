"""Tests for owner-seeded evidence retrieval; all transport is mocked."""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from scripts.hive_evidence import EvidenceRetrievalRejected, retrieve_approved_evidence
from scripts.hive_source_extract import ExtractionRejected


URL = "https://oem.example/specs/model.html"
ROBOTS_URL = "https://oem.example/robots.txt"
CONFIG = {
    "version": 1,
    "approved_hosts": ["oem.example"],
    "source_policies": [{
        "host": "oem.example",
        "automated_access_allowed": True,
        "terms_url": "https://oem.example/terms",
        "terms_reviewed_at": "2026-11-01",
        "terms_reviewed_by": "repository-owner",
        "terms_review_ref": "https://github.com/CarAutopsy/carautopsy/issues/37",
        "approved_urls": [{"url": URL, "variant_ids": ["synthetic.model-x"]}],
    }],
}


class HiveEvidenceAdapterTests(unittest.TestCase):
    def test_retrieves_only_owner_seeded_urls_and_returns_text_not_bytes(self):
        calls = []

        def fetcher(url, **kwargs):
            calls.append(url)
            if url == ROBOTS_URL:
                return SimpleNamespace(outcome="retrieved_unverified", body=b"User-agent: *\nAllow: /\n")
            self.assertNotIn("robots_allowed", kwargs)
            return SimpleNamespace(
                outcome="retrieved_unverified", body=b"official source bytes",
                content_type="text/plain", retrieved_at="2026-11-11T12:00:00Z",
            )

        evidence = retrieve_approved_evidence(
            variant_id="synthetic.model-x", config=CONFIG, fetcher=fetcher,
            extractor=lambda body, content_type, max_chars: SimpleNamespace(text=body.decode(), locators=("document",), locator_texts={"document": body.decode()}),
            today=date(2026, 11, 11),
        )
        self.assertEqual(calls, [ROBOTS_URL, URL])
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["url"], URL)
        self.assertTrue(evidence[0]["text"].startswith("[document]\n"))
        self.assertIn("official source bytes", evidence[0]["text"])
        self.assertNotIn("body", evidence[0])

    def test_empty_allowlist_is_a_hard_stop(self):
        config = dict(CONFIG, approved_hosts=[], source_policies=[])
        with self.assertRaisesRegex(EvidenceRetrievalRejected, "no owner-approved"):
            retrieve_approved_evidence(variant_id="synthetic.model-x", config=config, fetcher=Mock())

    def test_unapproved_host_or_url_never_reaches_fetcher(self):
        fetcher = Mock()
        with self.assertRaises(EvidenceRetrievalRejected):
            retrieve_approved_evidence(
                variant_id="synthetic.model-x",
                config=dict(CONFIG, source_policies=[dict(CONFIG["source_policies"][0], approved_urls=[{"url": "https://attacker.example/x", "variant_ids": ["synthetic.model-x"]}])]),
                fetcher=fetcher,
                today=date(2026, 11, 11),
            )
        fetcher.assert_not_called()

    def test_robots_denial_stops_target_fetch(self):
        calls = []

        def fetcher(url, **kwargs):
            calls.append(url)
            return SimpleNamespace(outcome="retrieved_unverified", body=b"User-agent: *\nDisallow: /\n")

        with self.assertRaises(EvidenceRetrievalRejected):
            retrieve_approved_evidence(variant_id="synthetic.model-x", config=CONFIG, fetcher=fetcher, today=date(2026, 11, 11))
        self.assertEqual(calls, [ROBOTS_URL])

    def test_unmatched_variant_has_no_source_requests(self):
        fetcher = Mock()
        with self.assertRaisesRegex(EvidenceRetrievalRejected, "no exact source URLs"):
            retrieve_approved_evidence(variant_id="other.variant", config=CONFIG, fetcher=fetcher)
        fetcher.assert_not_called()

    def test_retrieval_failure_stops_without_partial_bundle(self):
        fetcher = Mock(return_value=SimpleNamespace(outcome="rejected", body=None))
        with self.assertRaises(EvidenceRetrievalRejected):
            retrieve_approved_evidence(variant_id="synthetic.model-x", config=CONFIG, fetcher=fetcher, today=date(2026, 11, 11))

    def test_extraction_failure_stops_without_partial_bundle(self):
        def fetcher(url, **kwargs):
            if url == ROBOTS_URL:
                return SimpleNamespace(outcome="retrieved_unverified", body=b"User-agent: *\nAllow: /\n")
            return SimpleNamespace(
                outcome="retrieved_unverified", body=b"data",
                content_type="text/plain", retrieved_at="2026-11-11T12:00:00Z",
            )
        with self.assertRaises(EvidenceRetrievalRejected):
            retrieve_approved_evidence(variant_id="synthetic.model-x", config=CONFIG, fetcher=fetcher, extractor=Mock(side_effect=ExtractionRejected("bad")), today=date(2026, 11, 11))

    def test_unexpected_target_fetcher_exception_propagates(self):
        def fetcher(url, **kwargs):
            if url == ROBOTS_URL:
                return SimpleNamespace(outcome="retrieved_unverified", body=b"User-agent: *\nAllow: /\n")
            raise RuntimeError("unexpected fetcher defect")

        with self.assertRaisesRegex(RuntimeError, "unexpected fetcher defect"):
            retrieve_approved_evidence(
                variant_id="synthetic.model-x", config=CONFIG,
                fetcher=fetcher, today=date(2026, 11, 11),
            )

    def test_unexpected_extractor_exception_propagates(self):
        def fetcher(url, **kwargs):
            if url == ROBOTS_URL:
                return SimpleNamespace(outcome="retrieved_unverified", body=b"User-agent: *\nAllow: /\n")
            return SimpleNamespace(
                outcome="retrieved_unverified", body=b"data",
                content_type="text/plain", retrieved_at="2026-11-11T12:00:00Z",
            )

        with self.assertRaisesRegex(RuntimeError, "unexpected extractor defect"):
            retrieve_approved_evidence(
                variant_id="synthetic.model-x", config=CONFIG, fetcher=fetcher,
                extractor=Mock(side_effect=RuntimeError("unexpected extractor defect")),
                today=date(2026, 11, 11),
            )

    def test_duplicate_seed_urls_are_rejected(self):
        entry = dict(CONFIG["source_policies"][0], approved_urls=[{"url": URL, "variant_ids": ["synthetic.model-x"]}, {"url": URL, "variant_ids": ["synthetic.model-x"]}])
        fetcher = Mock()
        with self.assertRaisesRegex(EvidenceRetrievalRejected, "duplicate"):
            retrieve_approved_evidence(variant_id="synthetic.model-x", config=dict(CONFIG, source_policies=[entry]), fetcher=fetcher)
        fetcher.assert_not_called()


    def test_source_url_host_must_match_its_policy_entry(self):
        other_host_url = "https://b.example/specs/model.html"
        mismatched_entry = dict(CONFIG["source_policies"][0], approved_urls=[{
            "url": other_host_url, "variant_ids": ["synthetic.model-x"]
        }])
        fetcher = Mock()
        with self.assertRaisesRegex(EvidenceRetrievalRejected, "host does not match"):
            retrieve_approved_evidence(
                variant_id="synthetic.model-x",
                config=dict(CONFIG, source_policies=[mismatched_entry]),
                fetcher=fetcher,
            )
        fetcher.assert_not_called()


if __name__ == "__main__":
    unittest.main()
