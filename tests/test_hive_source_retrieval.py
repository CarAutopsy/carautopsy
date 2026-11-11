"""Security regression tests for the fail-closed Hive source retriever."""
import unittest
from unittest.mock import Mock

from scripts.hive_source_retrieval import fetch_source, _parse_source_url, _is_placeholder_identifier

HOSTS = {"oem.example"}
URL = "https://oem.example/specs/model.html"


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"source text"):
        self.status = status
        self.headers = headers or {"Content-Type": "text/html", "Content-Length": str(len(body))}
        self.body = body

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, amount=-1):
        if not self.body:
            return b""
        chunk, self.body = self.body[:amount], self.body[amount:]
        return chunk


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.request_args = None
        self.closed = False

    def request(self, method, path, headers):
        self.request_args = (method, path, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class HiveSourceRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.resolver = Mock(return_value=[(None, None, None, None, ("8.8.8.8", 443))])
        self.connection = FakeConnection(FakeResponse())
        self.factory = Mock(return_value=self.connection)
        self.robots = Mock(return_value=True)

    def fetch(self, url=URL, **overrides):
        options = {
            "approved_hosts": HOSTS, "robots_allowed": self.robots,
            "resolver": self.resolver, "connection_factory": self.factory,
        }
        options.update(overrides)
        return fetch_source(url, **options)

    def test_valid_approved_source_is_only_retrieved_unverified(self):
        result = self.fetch()
        self.assertEqual(result.outcome, "retrieved_unverified")
        self.assertIn("not_verified", result.reason)
        self.assertEqual(result.body, b"source text")
        self.factory.assert_called_once_with("oem.example", "8.8.8.8", 8.0)
        self.assertEqual(self.connection.request_args[0:2], ("GET", "/specs/model.html"))
        self.assertEqual(self.connection.request_args[2]["Host"], "oem.example")
        self.assertTrue(self.connection.closed)

    def test_http_scheme_is_rejected_before_dns_or_network(self):
        result = self.fetch("http://oem.example/specs")
        self.assertEqual(result.outcome, "rejected")
        self.assertIn("HTTPS", result.reason)
        self.resolver.assert_not_called()
        self.factory.assert_not_called()

    def test_unapproved_host_is_rejected(self):
        result = self.fetch("https://attacker.example/specs")
        self.assertEqual(result.outcome, "rejected")
        self.assertIn("allowlist", result.reason)
        self.resolver.assert_not_called()

    def test_empty_allowlist_fails_closed(self):
        result = self.fetch(approved_hosts=set())
        self.assertEqual(result.outcome, "rejected")
        self.assertIn("empty", result.reason)

    def test_credentials_and_nonstandard_port_are_rejected(self):
        for url in ("https://user:pass@oem.example/a", "https://oem.example:8443/a"):
            with self.subTest(url=url):
                self.assertEqual(self.fetch(url).outcome, "rejected")

    def test_ip_literal_is_rejected(self):
        result = self.fetch("https://8.8.8.8/specs", approved_hosts={"8.8.8.8"})
        self.assertEqual(result.outcome, "rejected")
        self.assertIn("IP-literal", result.reason)

    def test_kba_numeric_placeholder_is_rejected(self):
        self.assertTrue(_is_placeholder_identifier("https://oem.example/KBA-123456.html"))
        result = self.fetch("https://oem.example/docs/KBA-123456.html")
        self.assertIn("placeholder", result.reason)
        self.resolver.assert_not_called()

    def test_all_zero_configurator_identifier_is_rejected(self):
        result = self.fetch("https://oem.example/spec?id=00000000")
        self.assertIn("placeholder", result.reason)

    def test_private_dns_answer_is_rejected(self):
        resolver = Mock(return_value=[(None, None, None, None, ("127.0.0.1", 443))])
        result = self.fetch(resolver=resolver)
        self.assertIn("non-public", result.reason)
        self.factory.assert_not_called()

    def test_mixed_public_and_private_dns_answers_are_rejected(self):
        resolver = Mock(return_value=[
            (None, None, None, None, ("8.8.8.8", 443)),
            (None, None, None, None, ("10.0.0.8", 443)),
        ])
        result = self.fetch(resolver=resolver)
        self.assertIn("non-public", result.reason)
        self.factory.assert_not_called()

    def test_dns_failure_is_rejected(self):
        resolver = Mock(side_effect=OSError("dns down"))
        result = self.fetch(resolver=resolver)
        self.assertEqual(result.reason, "DNS resolution failed")

    def test_redirect_is_never_followed(self):
        self.connection.response = FakeResponse(status=302, headers={"Location": "http://127.0.0.1/"})
        result = self.fetch()
        self.assertEqual(result.reason, "redirect_not_followed")
        self.assertEqual(self.factory.call_count, 1)

    def test_unsupported_content_type_is_rejected(self):
        self.connection.response = FakeResponse(headers={"Content-Type": "application/json"})
        result = self.fetch()
        self.assertEqual(result.reason, "unsupported_content_type")

    def test_declared_oversized_response_is_rejected_before_read(self):
        self.connection.response = FakeResponse(headers={
            "Content-Type": "text/html", "Content-Length": "1001",
        })
        result = self.fetch(max_bytes=1000)
        self.assertEqual(result.reason, "response_too_large")

    def test_streamed_oversized_response_is_rejected(self):
        self.connection.response = FakeResponse(body=b"x" * 1001)
        result = self.fetch(max_bytes=1000)
        self.assertEqual(result.reason, "response_too_large")

    def test_robots_policy_is_mandatory_and_fail_closed(self):
        result = self.fetch(robots_allowed=None)
        self.assertIn("callback is required", result.reason)
        self.resolver.assert_not_called()
        result = self.fetch(robots_allowed=Mock(return_value=False))
        self.assertIn("did not permit", result.reason)
        self.resolver.assert_not_called()

    def test_robots_policy_exception_is_fail_closed(self):
        result = self.fetch(robots_allowed=Mock(side_effect=RuntimeError("policy error")))
        self.assertEqual(result.reason, "robots/terms policy check failed")
        self.resolver.assert_not_called()

    def test_timeout_is_bounded(self):
        result = self.fetch(timeout=31)
        self.assertIn("timeout", result.reason)
        self.resolver.assert_not_called()

    def test_safe_record_excludes_response_body(self):
        result = self.fetch()
        record = result.safe_record()
        self.assertNotIn("body", record)
        self.assertEqual(record["outcome"], "retrieved_unverified")

    def test_allowlist_does_not_accept_wildcards(self):
        with self.assertRaises(ValueError):
            _parse_source_url(URL, {"*.example"})


if __name__ == "__main__":
    unittest.main()
