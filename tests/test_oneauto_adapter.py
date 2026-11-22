"""Tests for the bounded, redacted One Auto API adapter (no network calls)."""
import json
import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import oneauto_adapter as adapter

FAKE_SECRET = "X" * 8  # synthetic placeholder; never a real credential


class FakeResponse:
    def __init__(self, status_code, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("malformed json body")
        return self._payload


class TimeoutResponse(FakeResponse):
    pass


def timeout_transport(url, headers, timeout):
    raise TimeoutError("timed out")


class RedactionTests(unittest.TestCase):
    def test_redact_removes_secret_and_bearer_tokens(self):
        text = f"Authorization: Bearer {FAKE_SECRET} api_key={FAKE_SECRET}"
        redacted = adapter.redact(text, FAKE_SECRET)
        self.assertNotIn(FAKE_SECRET, redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_safe_error_never_emits_secret(self):
        exc = ValueError(f"failed with {FAKE_SECRET}")
        self.assertNotIn(FAKE_SECRET, adapter.safe_error(exc, FAKE_SECRET))

    def test_missing_secret_is_detected_without_reading_value(self):
        self.assertIsNone(adapter.read_secret({}))
        self.assertFalse(adapter.secret_present({}))


class ProbeTests(unittest.TestCase):
    def test_missing_secret_probe_makes_no_request(self):
        result = adapter.connectivity_probe(environ={}, transport=timeout_transport)
        self.assertEqual(result["status"], "MISSING_SECRET")
        self.assertEqual(result["requests"], 0)
        self.assertFalse(result["austrian_price_verified"])

    def test_success_probe_is_redacted_and_bounded(self):
        calls = []

        def transport(url, headers, timeout):
            calls.append((url, timeout))
            self.assertNotIn(FAKE_SECRET, json.dumps(result_holder))
            return FakeResponse(200, {"status": "ok", "data": {"make": "VW"}})

        result_holder = {}
        result = adapter.connectivity_probe(secret=FAKE_SECRET, transport=transport)
        result_holder.update(result)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["requests"], 1)
        self.assertLessEqual(len(calls), adapter.MAX_PROBE_REQUESTS)
        self.assertNotIn(FAKE_SECRET, json.dumps(result))
        self.assertIsNotNone(result["response_hash"])
        self.assertEqual(result["price_tier_ceiling"], "enrichment_only")

    def test_http_401_is_auth_denied(self):
        result = adapter.connectivity_probe(secret=FAKE_SECRET,
                                            transport=lambda *a: FakeResponse(401))
        self.assertEqual(result["status"], "AUTH_DENIED")

    def test_timeout_is_classified(self):
        result = adapter.connectivity_probe(secret=FAKE_SECRET, transport=timeout_transport)
        self.assertEqual(result["status"], "TIMEOUT")
        self.assertNotIn(FAKE_SECRET, json.dumps(result))

    def test_malformed_json_is_classified(self):
        result = adapter.connectivity_probe(secret=FAKE_SECRET,
                                            transport=lambda *a: FakeResponse(200, raise_json=True))
        self.assertEqual(result["status"], "MALFORMED_RESPONSE")


class RateLimitTests(unittest.TestCase):
    def test_rate_limiter_waits_minimum_interval(self):
        now = [0.0]
        sleeps = []
        limiter = adapter.RateLimiter(2.0, clock=lambda: now[0], sleeper=sleeps.append)
        limiter.acquire()
        now[0] = 0.5
        limiter.acquire()
        self.assertEqual(sleeps, [1.5])

    def test_backoff_is_exponential_and_bounded(self):
        self.assertEqual(adapter.backoff_delay(1, 0.5, 8.0), 0.5)
        self.assertEqual(adapter.backoff_delay(2, 0.5, 8.0), 1.0)
        self.assertEqual(adapter.backoff_delay(10, 0.5, 8.0), 8.0)


class EnrichmentTests(unittest.TestCase):
    def test_missing_secret_raises(self):
        with self.assertRaises(adapter.OneAutoError) as ctx:
            adapter.fetch_enrichment(environ={})
        self.assertEqual(ctx.exception.code, "MISSING_SECRET")

    def test_whitelist_and_provenance_are_bounded(self):
        payload = {"make": "VW", "model": "Golf", "secret": FAKE_SECRET,
                   "vin": "WVWZZZ", "price_candidate": 20000}
        response = adapter.fetch_enrichment(
            secret=FAKE_SECRET,
            transport=lambda *a: FakeResponse(200, payload),
            limiter=adapter.RateLimiter(0, clock=lambda: 0.0, sleeper=lambda _: None),
        )
        self.assertIn("make", response["data"])
        self.assertNotIn("vin", response["data"])
        self.assertNotIn("secret", response["data"])
        self.assertNotIn(FAKE_SECRET, json.dumps(response))
        self.assertEqual(response["provenance"]["provider"], "oneautoapi")
        self.assertFalse(response["austrian_price_verified"])
        self.assertTrue(response["review_required"])

    def test_transient_429_then_success_uses_backoff(self):
        sleeps = []
        responses = [FakeResponse(429), FakeResponse(200, {"make": "VW"})]

        def transport(url, headers, timeout):
            return responses.pop(0)

        result = adapter.fetch_enrichment(
            secret=FAKE_SECRET, transport=transport,
            limiter=adapter.RateLimiter(0, clock=lambda: 0.0, sleeper=lambda _: None),
            sleeper=sleeps.append,
        )
        self.assertEqual(result["requests"], 2)
        self.assertEqual(len(sleeps), 1)

    def test_auth_denied_and_malformed_payload(self):
        with self.assertRaises(adapter.OneAutoError) as ctx:
            adapter.fetch_enrichment(secret=FAKE_SECRET, transport=lambda *a: FakeResponse(403),
                                     limiter=adapter.RateLimiter(0, clock=lambda: 0.0))
        self.assertEqual(ctx.exception.code, "AUTH_DENIED")

        with self.assertRaises(adapter.OneAutoError) as ctx:
            adapter.fetch_enrichment(
                secret=FAKE_SECRET,
                transport=lambda *a: FakeResponse(200, raise_json=True),
                limiter=adapter.RateLimiter(0, clock=lambda: 0.0),
            )
        self.assertEqual(ctx.exception.code, "MALFORMED_RESPONSE")


if __name__ == "__main__":
    unittest.main()
