"""Fail-closed HTTPS source retrieval with DNS-pinned connections.

HTTP success is recorded as retrieved_unverified; it never proves claim support.
The caller must supply a review-controlled exact-host allowlist and an explicit
robots/terms policy callback. Empty allowlists and missing policy callbacks deny.
"""
from __future__ import annotations

import http.client
import io
import ipaddress
import queue
import re
import select
import socket
import threading
import ssl
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable
from urllib.parse import unquote, urlsplit, urlunsplit

MAX_URL_CHARS = 2_048
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 8.0

# Timed-out system calls cannot be cancelled safely. Bound their outstanding
# workers so repeated stalls cannot exhaust the process with daemon threads.
MAX_OUTSTANDING_POLICY_WORKERS = 4
MAX_OUTSTANDING_DNS_WORKERS = 4
_POLICY_WORKER_SLOTS = threading.BoundedSemaphore(MAX_OUTSTANDING_POLICY_WORKERS)
_DNS_WORKER_SLOTS = threading.BoundedSemaphore(MAX_OUTSTANDING_DNS_WORKERS)
ALLOWED_CONTENT_TYPES = {"text/html", "text/plain", "application/pdf"}


@dataclass(frozen=True)
class RetrievalResult:
    url: str
    outcome: str
    reason: str
    retrieved_at: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    body: bytes | None = None
    resolved_ip: str | None = None

    def safe_record(self) -> dict:
        """Return ledger-safe metadata without response bytes or URL secrets."""
        value = asdict(self)
        value["url"] = _safe_url_for_record(self.url)
        value.pop("body", None)
        return value


def _safe_url_for_record(url: str) -> str:
    """Remove userinfo, query values, and fragments before diagnostic persistence."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if not host:
            return "[invalid-url]"
        try:
            port = parsed.port
        except ValueError:
            return "[invalid-url]"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host + (f":{port}" if port is not None else "")
        query = "[redacted]" if parsed.query else ""
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))
    except (TypeError, ValueError):
        return "[invalid-url]"


class RetrievalDenied(ValueError):
    """Raised for invalid policy/configuration before any outbound request."""

def _start_bounded_worker(slots, name: str, target: Callable[[], None]) -> None:
    """Start a daemon worker only when a bounded outstanding slot is available.

    The slot belongs to the worker, not the waiting caller: a timed-out caller
    cannot release capacity while its uncancellable callback is still running.
    """
    if not slots.acquire(blocking=False):
        raise RetrievalDenied(f"{name} worker capacity exhausted")
    def run():
        try:
            target()
        finally:
            slots.release()
    worker = threading.Thread(target=run, name=name, daemon=True)
    try:
        worker.start()
    except BaseException as exc:
        slots.release()
        raise RetrievalDenied(f"{name} worker could not start") from exc


def _normalise_allowlist(approved_hosts: Iterable[str]) -> set[str]:
    if isinstance(approved_hosts, (str, bytes)) or approved_hosts is None:
        raise RetrievalDenied("approved hosts must be an explicit collection of exact hostnames")
    hosts = set()
    for host in approved_hosts:
        if not isinstance(host, str) or not host or host != host.strip():
            raise RetrievalDenied("approved host entries must be exact hostnames")
        normal = host.rstrip(".").lower()
        if not normal or "*" in normal or "/" in normal or ":" in normal:
            raise RetrievalDenied("wildcards, ports and URL paths are forbidden in the allowlist")
        hosts.add(normal)
    if not hosts:
        raise RetrievalDenied("approved-host allowlist is empty; retrieval is disabled")
    return hosts


def _parse_source_url(url: str, approved_hosts: Iterable[str]):
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS:
        raise RetrievalDenied("source URL is missing or exceeds the URL limit")
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise RetrievalDenied("source URL contains control characters")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise RetrievalDenied("source URL is malformed") from exc
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() != "https":
        raise RetrievalDenied("only HTTPS source URLs are permitted")
    if not host or parsed.username is not None or parsed.password is not None:
        raise RetrievalDenied("source URL must have a hostname and no credentials")
    if port not in (None, 443):
        raise RetrievalDenied("non-standard HTTPS ports are forbidden")
    if parsed.fragment:
        raise RetrievalDenied("URL fragments are not sent to the source server")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise RetrievalDenied("IP-literal source URLs are forbidden")
    if host not in _normalise_allowlist(approved_hosts):
        raise RetrievalDenied("source hostname is not on the approved-host allowlist")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return host, path


def _decode_placeholder_component(value: str) -> str:
    """Decode once before splitting delimiters; reject malformed or nested escapes."""
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        raise RetrievalDenied("source URL contains malformed percent encoding")
    try:
        decoded = unquote(value, errors="strict")
    except UnicodeDecodeError as exc:
        raise RetrievalDenied("source URL contains invalid encoded text") from exc
    if re.search(r"%[0-9a-fA-F]{2}", decoded):
        raise RetrievalDenied("source URL contains nested percent encoding")
    return decoded


def _is_placeholder_identifier(url: str) -> bool:
    """Reject synthetic identifiers after decoding encoded path/query delimiters."""
    parsed = urlsplit(url)
    decoded_path = _decode_placeholder_component(parsed.path)
    decoded_query = _decode_placeholder_component(parsed.query)
    segments = [part for part in decoded_path.split("/") if part]
    for segment in segments:
        lower = segment.lower().split(".", 1)[0]
        if lower.startswith("kba-") and lower[4:].isdigit() and len(lower[4:]) >= 4:
            return True
        compact = lower.replace("-", "").replace("_", "")
        if len(compact) >= 6 and set(compact) == {"0"}:
            return True
    for value in re.split(r"[&;]", decoded_query):
        key, _, item = value.partition("=")
        compact = item.replace("-", "").replace("_", "")
        if key.lower() in {"configurator_id", "configuratorid", "id"} and len(compact) >= 6 and set(compact) == {"0"}:
            return True
    return False



def _check_robots_policy_before_deadline(url: str, policy, deadline: float, clock) -> None:
    """Run the policy callback without allowing it to exceed the retrieval deadline."""
    result_queue = queue.Queue(maxsize=1)

    def check():
        try:
            result_queue.put((True, policy(url)))
        except BaseException as exc:
            result_queue.put((False, exc))

    # Policy callbacks may perform network I/O and cannot be safely cancelled.
    # Capacity stays occupied until the callback actually exits, even if this
    # request times out and discards its result.
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError("retrieval deadline exceeded during robots/terms policy check")
    _start_bounded_worker(_POLICY_WORKER_SLOTS, "hive-robots-policy", check)
    try:
        succeeded, value = result_queue.get(timeout=remaining)
    except queue.Empty as exc:
        raise TimeoutError("retrieval deadline exceeded during robots/terms policy check") from exc
    if not succeeded:
        raise RetrievalDenied("robots/terms policy check failed") from value
    if value is not True:
        raise RetrievalDenied("robots/terms policy did not permit this URL")


def _resolve_public_addresses_before_deadline(host: str, resolver, deadline: float, clock) -> list[str]:
    """Run blocking system DNS in a daemon worker and stop waiting at the shared deadline."""
    result_queue = queue.Queue(maxsize=1)

    def resolve():
        try:
            result_queue.put((True, resolver(host, 443, type=socket.SOCK_STREAM)))
        except BaseException as exc:
            result_queue.put((False, exc))

    # getaddrinfo cannot be cancelled safely. Capacity remains occupied until
    # the resolver exits, even when this request has stopped waiting.
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError("retrieval deadline exceeded during DNS resolution")
    _start_bounded_worker(_DNS_WORKER_SLOTS, "hive-dns-resolution", resolve)
    try:
        succeeded, value = result_queue.get(timeout=remaining)
    except queue.Empty as exc:
        raise TimeoutError("retrieval deadline exceeded during DNS resolution") from exc
    if not succeeded:
        raise RetrievalDenied("DNS resolution failed") from value
    return _validate_resolved_addresses(value)


def _validate_resolved_addresses(records) -> list[str]:
    """Validate every DNS answer and return unique public IPs only."""
    addresses = []
    for record in records:
        try:
            address = record[4][0].split("%", 1)[0]
            parsed = ipaddress.ip_address(address)
        except (IndexError, KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RetrievalDenied("DNS returned an invalid address record") from exc
        if not parsed.is_global:
            raise RetrievalDenied("DNS returned a non-public destination address")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise RetrievalDenied("DNS returned no usable addresses")
    return addresses


def _response_body_socket(response, connection):
    """Find the deadline-aware socket retained by HTTPResponse."""
    sock = getattr(connection, "sock", None)
    if sock is not None:
        return sock
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    return getattr(raw, "deadline_socket", None)


class _DeadlineSocketReader(io.RawIOBase):
    """Raw reader that reapplies the absolute deadline before every receive."""

    def __init__(self, deadline_socket):
        super().__init__()
        self.deadline_socket = deadline_socket

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.closed:
            raise ValueError("I/O operation on closed reader")
        self.deadline_socket._apply_deadline()
        return self.deadline_socket._socket.recv_into(buffer)

    def close(self):
        if not self.closed:
            try:
                super().close()
            finally:
                self.deadline_socket._reader_closed()


class _DeadlineSocket:
    """Socket facade enforcing one absolute deadline inside HTTPResponse reads."""

    def __init__(self, sock, deadline, clock):
        self._socket = sock
        self._deadline = deadline
        self._clock = clock
        self._io_refs = 0
        self._closed = False
        self._socket_closed = False

    def _reader_closed(self):
        self._io_refs = max(0, self._io_refs - 1)
        if self._closed and self._io_refs == 0:
            self._close_socket()

    def _close_socket(self):
        if not self._socket_closed:
            self._socket_closed = True
            self._socket.close()

    def _apply_deadline(self):
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise socket.timeout("retrieval deadline exceeded")
        self._socket.settimeout(remaining)

    def settimeout(self, _timeout):
        """Preserve the absolute retrieval deadline instead of accepting a relative reset."""
        self._apply_deadline()

    def sendall(self, data, flags=0):
        self._apply_deadline()
        if flags:
            return self._socket.sendall(data, flags)
        return self._socket.sendall(data)

    def makefile(self, mode="r", buffering=None, **kwargs):
        if mode not in ("rb", "r"):
            return self._socket.makefile(mode, buffering, **kwargs)
        if self._closed:
            raise OSError("cannot create a file from a closed deadline socket")
        self._io_refs += 1
        reader = _DeadlineSocketReader(self)
        return io.BufferedReader(reader, buffer_size=buffering or io.DEFAULT_BUFFER_SIZE)

    def close(self):
        self._closed = True
        if self._io_refs == 0:
            self._close_socket()

    def __getattr__(self, name):
        return getattr(self._socket, name)


def _resolve_public_addresses(host: str, resolver=socket.getaddrinfo) -> list[str]:
    try:
        records = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise RetrievalDenied("DNS resolution failed") from exc
    addresses = []
    for record in records:
        address = record[4][0].split("%", 1)[0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise RetrievalDenied("DNS returned an invalid address") from exc
        if not parsed.is_global:
            raise RetrievalDenied("DNS returned a non-public destination address")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise RetrievalDenied("DNS returned no usable addresses")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that dials a previously validated IP, retaining host TLS identity."""
    def __init__(self, hostname: str, pinned_ip: str, timeout: float):
        super().__init__(hostname, port=443, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip

    def connect(self):
        deadline = getattr(self, "_retrieval_deadline", None)
        clock = getattr(self, "_retrieval_clock", time.monotonic)
        remaining = deadline - clock() if deadline is not None else self.timeout
        if remaining <= 0:
            raise socket.timeout("retrieval deadline exceeded before TCP connect")
        raw = socket.create_connection((self._pinned_ip, 443), remaining, self.source_address)
        if deadline is None:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
            return

        wrapped = self._context.wrap_socket(
            raw, server_hostname=self.host, do_handshake_on_connect=False
        )
        try:
            wrapped.setblocking(False)
            while True:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise socket.timeout("retrieval deadline exceeded during TLS handshake")
                try:
                    wrapped.do_handshake()
                    break
                except ssl.SSLWantReadError:
                    if wrapped.pending():
                        continue
                    readable, _, _ = select.select([wrapped], [], [], remaining)
                    if not readable:
                        raise socket.timeout("retrieval deadline exceeded during TLS handshake")
                except ssl.SSLWantWriteError:
                    _, writable, _ = select.select([], [wrapped], [], remaining)
                    if not writable:
                        raise socket.timeout("retrieval deadline exceeded during TLS handshake")
            remaining = deadline - clock()
            if remaining <= 0:
                raise socket.timeout("retrieval deadline exceeded after TLS handshake")
            wrapped.settimeout(remaining)
            self.sock = _DeadlineSocket(wrapped, deadline, clock)
        except BaseException:
            wrapped.close()
            raise


def fetch_source(
    url: str,
    *,
    approved_hosts: Iterable[str],
    robots_allowed: Callable[[str], bool] | None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_RESPONSE_BYTES,
    resolver=socket.getaddrinfo,
    connection_factory=None,
    clock=time.monotonic,
) -> RetrievalResult:
    """Fetch one approved HTTPS URL without redirects, proxies or DNS re-resolution.

    robots_allowed must be an owner-controlled policy check that returns True only
    when robots.txt and source terms permit this exact URL. It must itself fail closed.
    """
    try:
        host, path = _parse_source_url(url, approved_hosts)
        if _is_placeholder_identifier(url):
            raise RetrievalDenied("source URL contains a placeholder identifier")
        if timeout <= 0 or timeout > 30:
            raise RetrievalDenied("timeout must be greater than 0 and at most 30 seconds")
        if max_bytes <= 0 or max_bytes > MAX_RESPONSE_BYTES:
            raise RetrievalDenied("response limit is outside the permitted bound")
        deadline = clock() + timeout
        if robots_allowed is None:
            raise RetrievalDenied("robots/terms policy callback is required")
        _check_robots_policy_before_deadline(url, robots_allowed, deadline, clock)
        addresses = _resolve_public_addresses_before_deadline(host, resolver, deadline, clock)
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("retrieval deadline exceeded")
        pinned_ip = addresses[0]
        factory = connection_factory or _PinnedHTTPSConnection
        connection = factory(host, pinned_ip, min(timeout, remaining))
        connection._retrieval_deadline = deadline
        connection._retrieval_clock = clock
        response = None
        try:
            remaining = deadline - clock()
            if remaining <= 0:
                raise TimeoutError("retrieval deadline exceeded before request")
            sock = getattr(connection, "sock", None)
            if sock is not None:
                sock.settimeout(remaining)
            connection.request("GET", path, headers={
                "Host": host,
                "User-Agent": "CarAutopsy-Research-Bot/1.0 (+https://github.com/CarAutopsy/carautopsy)",
                "Accept": "text/html, text/plain, application/pdf",
                "Accept-Encoding": "identity",
                "Connection": "close",
            })
            remaining = deadline - clock()
            if remaining <= 0:
                raise TimeoutError("retrieval deadline exceeded")
            sock = getattr(connection, "sock", None)
            if sock is not None:
                sock.settimeout(remaining)
            response = connection.getresponse()
            status = response.status
            if 300 <= status < 400:
                return RetrievalResult(url, "rejected", "redirect_not_followed", status_code=status, resolved_ip=pinned_ip)
            if status < 200 or status >= 300:
                return RetrievalResult(url, "rejected", "http_status_not_success", status_code=status, resolved_ip=pinned_ip)
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            content_encoding = response.getheader("Content-Encoding", "identity").strip().lower()
            if content_encoding not in ("", "identity"):
                return RetrievalResult(url, "rejected", "unsupported_content_encoding", status_code=status, content_type=content_type or None, resolved_ip=pinned_ip)
            if content_type not in ALLOWED_CONTENT_TYPES:
                return RetrievalResult(url, "rejected", "unsupported_content_type", status_code=status, content_type=content_type or None, resolved_ip=pinned_ip)
            declared = response.getheader("Content-Length")
            declared_length = None
            if declared is not None:
                try:
                    declared_length = int(declared)
                    if declared_length < 0 or declared_length > max_bytes:
                        return RetrievalResult(url, "rejected", "response_too_large", status_code=status, content_type=content_type, resolved_ip=pinned_ip)
                except ValueError:
                    return RetrievalResult(url, "rejected", "invalid_content_length", status_code=status, content_type=content_type, resolved_ip=pinned_ip)
            chunks = []
            total = 0
            while True:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise TimeoutError("retrieval deadline exceeded")
                if response.isclosed():
                    break
                sock = _response_body_socket(response, connection)
                if sock is None:
                    raise RetrievalDenied("HTTP response socket is unavailable for deadline-bounded reads")
                sock.settimeout(remaining)
                read_chunk = getattr(response, "read1", None)
                if not callable(read_chunk):
                    raise RetrievalDenied("HTTP response does not support deadline-bounded reads")
                chunk = read_chunk(min(65_536, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    return RetrievalResult(url, "rejected", "response_too_large", status_code=status, content_type=content_type, resolved_ip=pinned_ip)
                chunks.append(chunk)
            if declared_length is not None and total != declared_length:
                return RetrievalResult(url, "rejected", "incomplete_response_body", status_code=status, content_type=content_type, resolved_ip=pinned_ip)
            return RetrievalResult(
                url, "retrieved_unverified", "http_response_retrieved_but_claim_support_not_verified",
                datetime.now(timezone.utc).isoformat(), status, content_type, b"".join(chunks), pinned_ip,
            )
        finally:
            if response is not None:
                response.close()
            connection.close()
    except RetrievalDenied as exc:
        return RetrievalResult(url if isinstance(url, str) else "", "rejected", str(exc))
    except (socket.timeout, TimeoutError):
        return RetrievalResult(url if isinstance(url, str) else "", "rejected", "request_timeout")
    except (OSError, ssl.SSLError, http.client.HTTPException):
        return RetrievalResult(url if isinstance(url, str) else "", "rejected", "network_or_tls_failure")


def validate_candidate_sources(urls: list[str], **fetch_options) -> list[dict]:
    """Return one safe metadata record per URL; no result implies claim verification."""
    options = dict(fetch_options)
    approved_hosts = options.get("approved_hosts")
    if approved_hosts is not None and not isinstance(approved_hosts, (str, bytes)):
        try:
            options["approved_hosts"] = tuple(approved_hosts)
        except TypeError:
            # Preserve the retriever's normal fail-closed validation behavior.
            pass
    results = []
    for url in urls:
        result = fetch_source(url, **options)
        results.append(result.safe_record())
    return results
