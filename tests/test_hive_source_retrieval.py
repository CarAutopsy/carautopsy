"""Security regression tests for the fail-closed Hive source retriever."""
import http.client
import socket
import ssl
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.hive_source_retrieval import fetch_source, validate_candidate_sources, _parse_source_url, _is_placeholder_identifier

HOSTS = {"oem.example"}
URL = "https://oem.example/specs/model.html"


class FakeSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"source text"):
        self.status = status
        self.headers = headers or {"Content-Type": "text/html", "Content-Length": str(len(body))}
        self.body = body
        self.socket = FakeSocket()
        self.fp = SimpleNamespace(raw=SimpleNamespace(deadline_socket=self.socket))

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, amount=-1):
        if not self.body:
            return b""
        chunk, self.body = self.body[:amount], self.body[amount:]
        return chunk

    def read1(self, amount=-1):
        return self.read(amount)

    def isclosed(self):
        return not self.body

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.request_args = None
        self.closed = False
        self.sock = FakeSocket()

    def request(self, method, path, headers):
        self.request_args = (method, path, headers)

    def getresponse(self):
        self.sock = None  # http.client may release this reference after headers
        return self.response

    def close(self):
        self.closed = True


class HiveSourceRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.resolver = Mock(return_value=[(None, None, None, None, ("8.8.8.8", 443))])
        self.connection = FakeConnection(FakeResponse())
        self.factory = Mock(return_value=self.connection)

    def fetch(self, url=URL, **overrides):
        options = {
            "approved_hosts": HOSTS,
            "resolver": self.resolver,
        }
        options.update(overrides)
        with patch("scripts.hive_source_retrieval._PinnedHTTPSConnection", self.factory):
            return fetch_source(url, **options)

    def test_valid_approved_source_is_only_retrieved_unverified(self):
        result = self.fetch(clock=lambda: 0.0)
        self.assertEqual(result.outcome, "retrieved_unverified")
        self.assertIn("not_verified", result.reason)
        self.assertEqual(result.body, b"source text")
        self.factory.assert_called_once()
        self.assertEqual(self.factory.call_args.args[:2], ("oem.example", "8.8.8.8"))
        self.assertEqual(self.factory.call_args.args[2], 8.0)
        self.assertEqual(self.connection.request_args[0:2], ("GET", "/specs/model.html"))
        self.assertEqual(self.connection.request_args[2]["Host"], "oem.example")
        user_agent = self.connection.request_args[2]["User-Agent"]
        self.assertIn("https://github.com/CarAutopsy/carautopsy", user_agent)
        self.assertNotIn("@", user_agent)
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

    def test_percent_encoded_placeholder_identifiers_are_rejected(self):
        urls = (
            "https://oem.example/KBA-%31%32%33%34%35%36.html",
            "https://oem.example/spec?id=%30%30%30%30%30%30",
            "https://oem.example/spec?%69%64=000000",
        )
        for url in urls:
            with self.subTest(url=url):
                result = self.fetch(url)
                self.assertIn("placeholder", result.reason)
        self.resolver.assert_not_called()

    def test_malformed_and_nested_percent_encoding_are_rejected(self):
        for url in (
            "https://oem.example/spec/KBA-%ZZ1234.html",
            "https://oem.example/spec?id=%253030303030",
        ):
            with self.subTest(url=url):
                result = self.fetch(url)
                self.assertEqual(result.outcome, "rejected")
        self.resolver.assert_not_called()

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

    def test_dns_answer_count_above_limit_is_rejected_before_connect(self):
        from scripts.hive_source_retrieval import MAX_DNS_ANSWERS

        record = (None, None, None, None, ("8.8.8.8", 443))
        resolver = Mock(return_value=[record] * (MAX_DNS_ANSWERS + 1))
        result = self.fetch(resolver=resolver)
        self.assertEqual(result.outcome, "rejected")
        self.assertIn("answer count", result.reason)
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
        self.connection.response = FakeResponse(headers={"Content-Type": "text/html"}, body=b"x" * 1001)
        result = self.fetch(max_bytes=1000)
        self.assertEqual(result.reason, "response_too_large")

    def test_transport_api_rejects_caller_supplied_policy_callbacks(self):
        with self.assertRaises(TypeError):
            self.fetch(robots_allowed=lambda _url: True)
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

    def test_safe_record_redacts_url_credentials_and_query_values(self):
        result = self.fetch("https://alice:supersecret@oem.example/spec?token=private")
        record = result.safe_record()
        self.assertNotIn("alice", record["url"])
        self.assertNotIn("supersecret", record["url"])
        self.assertNotIn("private", record["url"])
        self.assertEqual(record["url"], "https://oem.example/spec?[redacted]")

    def test_declared_content_length_mismatch_is_rejected(self):
        self.connection.response = FakeResponse(
            headers={"Content-Type": "text/html", "Content-Length": "20"},
            body=b"short",
        )
        result = self.fetch()
        self.assertEqual(result.reason, "incomplete_response_body")

    def test_total_deadline_stops_a_trickling_response(self):
        now = {"value": 0.0}
        response = FakeResponse(headers={"Content-Type": "text/html"}, body=b"x")
        def trickle(amount):
            now["value"] += 2.0
            return response.read(amount)
        response.read1 = trickle
        self.connection.response = response
        result = self.fetch(timeout=1.0, clock=lambda: now["value"])
        self.assertEqual(result.reason, "request_timeout")


    def test_dns_resolution_is_bounded_by_total_deadline(self):
        def stalled_resolver(*args, **kwargs):
            time.sleep(0.1)
            return [(None, None, None, None, ("8.8.8.8", 443))]
        result = self.fetch(timeout=0.01, resolver=stalled_resolver)
        self.assertEqual(result.reason, "request_timeout")
        self.factory.assert_not_called()


    def test_stalled_dns_workers_are_capped_until_resolvers_exit(self):
        from scripts import hive_source_retrieval as retrieval

        slots = threading.BoundedSemaphore(2)
        release = threading.Event()
        both_started = threading.Event()
        started = {"count": 0}
        lock = threading.Lock()

        def stalled_resolver(*args, **kwargs):
            with lock:
                started["count"] += 1
                if started["count"] == 2:
                    both_started.set()
            release.wait()
            return [(None, None, None, None, ("8.8.8.8", 443))]

        try:
            with patch.object(retrieval, "_DNS_WORKER_SLOTS", slots):
                first = self.fetch(timeout=0.02, resolver=stalled_resolver)
                second = self.fetch(timeout=0.02, resolver=stalled_resolver)
                self.assertTrue(both_started.wait(1), "both DNS workers did not start")
                third = self.fetch(timeout=0.02, resolver=stalled_resolver)
                self.assertEqual(first.reason, "request_timeout")
                self.assertEqual(second.reason, "request_timeout")
                self.assertIn("worker capacity exhausted", third.reason)
                self.assertEqual(started["count"], 2)
                self.factory.assert_not_called()
        finally:
            release.set()
        self.assertTrue(slots.acquire(timeout=1))
        self.assertTrue(slots.acquire(timeout=1))
        slots.release()
        slots.release()

    def test_response_socket_is_used_after_connection_socket_is_released(self):
        result = self.fetch()
        self.assertEqual(result.outcome, "retrieved_unverified")
        self.assertTrue(self.connection.response.socket.timeouts)
        self.assertTrue(all(value > 0 for value in self.connection.response.socket.timeouts))

    def test_closed_content_length_response_finishes_without_socket_lookup(self):
        self.connection.response = FakeResponse(body=b"complete")
        result = self.fetch()
        self.assertEqual(result.outcome, "retrieved_unverified")
        self.assertEqual(result.body, b"complete")

    def test_deadline_socket_bounds_slow_header_or_chunk_framing_reads(self):
        from scripts.hive_source_retrieval import _DeadlineSocket
        client, server = socket.socketpair()
        deadline = time.monotonic() + 0.08
        wrapped = _DeadlineSocket(client, deadline, time.monotonic)
        reader = wrapped.makefile("rb")

        def drip_bytes():
            try:
                for byte in b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n":
                    server.sendall(bytes([byte]))
                    time.sleep(0.02)
            except OSError:
                pass

        worker = threading.Thread(target=drip_bytes, daemon=True)
        worker.start()
        started = time.monotonic()
        try:
            with self.assertRaises(socket.timeout):
                reader.readline()
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            reader.close()
            wrapped.close()
            server.close()
            worker.join(timeout=0.2)

    def test_candidate_source_batch_materializes_one_shot_allowlist(self):
        urls = [URL, "https://oem.example/specs/second.html"]
        def factory(host, pinned_ip, timeout):
            return FakeConnection(FakeResponse())
        with patch("scripts.hive_source_retrieval._PinnedHTTPSConnection", side_effect=factory):
            results = validate_candidate_sources(
                urls,
                approved_hosts=(host for host in HOSTS),
                resolver=self.resolver,
            )
        self.assertEqual([item["outcome"] for item in results], ["retrieved_unverified"] * 2)

    def test_real_http_response_reads_body_after_connection_close(self):
        from scripts.hive_source_retrieval import _DeadlineSocket

        client, server = socket.socketpair()
        wrapped = _DeadlineSocket(client, time.monotonic() + 1.0, time.monotonic)
        response = http.client.HTTPResponse(wrapped)
        try:
            server.sendall(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: 12\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                b"hello world!"
            )
            response.begin()
            wrapped.close()  # HTTPConnection.getresponse() closes this when will_close.
            self.assertEqual(response.read1(64), b"hello world!")
            self.assertTrue(response.isclosed())
        finally:
            response.close()
            wrapped.close()
            server.close()
        self.assertEqual(client.fileno(), -1)

    def test_response_reader_keeps_socket_alive_after_connection_close(self):
        from scripts.hive_source_retrieval import _DeadlineSocket

        client, server = socket.socketpair()
        wrapped = _DeadlineSocket(client, time.monotonic() + 1.0, time.monotonic)
        reader = wrapped.makefile("rb")
        wrapped.close()  # Mirrors HTTPConnection closing a Connection: close socket.
        try:
            server.sendall(b"response body")
            self.assertEqual(reader.read(13), b"response body")
        finally:
            reader.close()
            server.close()
        self.assertEqual(client.fileno(), -1)

    def test_tls_handshake_observes_shared_deadline(self):
        from scripts.hive_source_retrieval import _PinnedHTTPSConnection

        class StalledTLS:
            def __init__(self):
                self.closed = False
                self.blocking = None

            def setblocking(self, value):
                self.blocking = value

            def do_handshake(self):
                raise ssl.SSLWantReadError()

            def pending(self):
                return 0

            def close(self):
                self.closed = True

        connection = _PinnedHTTPSConnection("oem.example", "8.8.8.8", 5.0)
        connection._retrieval_deadline = 10.0
        connection._retrieval_clock = lambda: 0.0
        raw_socket = Mock()
        tls_socket = StalledTLS()
        with (
            patch("scripts.hive_source_retrieval.socket.create_connection", return_value=raw_socket),
            patch.object(connection, "_context") as context,
            patch("scripts.hive_source_retrieval.select.select", return_value=([], [], [])) as wait,
        ):
            context.wrap_socket.return_value = tls_socket
            with self.assertRaises(socket.timeout):
                connection.connect()
        wait.assert_called_once_with([tls_socket], [], [], 10.0)
        self.assertTrue(tls_socket.closed)

    def test_pinned_transport_dials_validated_ip_and_keeps_hostname_for_tls(self):
        from scripts.hive_source_retrieval import _PinnedHTTPSConnection
        connection = _PinnedHTTPSConnection("oem.example", "8.8.8.8", 3)
        raw_socket = object()
        wrapped_socket = object()
        with patch("scripts.hive_source_retrieval.socket.create_connection", return_value=raw_socket) as dial, \
             patch.object(connection, "_context") as tls:
            tls.wrap_socket.return_value = wrapped_socket
            connection.connect()
        dial.assert_called_once_with(("8.8.8.8", 443), 3, None)
        tls.wrap_socket.assert_called_once_with(raw_socket, server_hostname="oem.example")
        self.assertIs(connection.sock, wrapped_socket)

    def test_allowlist_does_not_accept_wildcards(self):
        with self.assertRaises(ValueError):
            _parse_source_url(URL, {"*.example"})


if __name__ == "__main__":
    unittest.main()
