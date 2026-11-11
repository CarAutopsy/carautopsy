"""Fail-closed HTTPS source retrieval with DNS-pinned connections.

HTTP success is recorded as retrieved_unverified; it never proves claim support.
The caller must supply a review-controlled exact-host allowlist and an explicit
robots/terms policy callback. Empty allowlists and missing policy callbacks deny.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable
from urllib.parse import urlsplit

MAX_URL_CHARS = 2_048
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 8.0
ALLOWED_CONTENT_TYPES = {"text/html", "text/plain", "application/pdf"}
MAX_REDIRECTS = 0


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
        """Return metadata suitable for a ledger; never include response bytes."""
        value = asdict(self)
        value.pop("body", None)
        return value


class RetrievalDenied(ValueError):
    """Raised for invalid policy/configuration before any outbound request."""


def _normalise_allowlist(approved_hosts: Iterable[str]) -> set[str]:
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


def _is_placeholder_identifier(url: str) -> bool:
    """Reject known synthetic KBA filenames and all-zero identifier segments."""
    parsed = urlsplit(url)
    segments = [part for part in parsed.path.split("/") if part]
    for segment in segments:
        lower = segment.lower().split(".", 1)[0]
        if lower.startswith("kba-") and lower[4:].isdigit() and len(lower[4:]) >= 4:
            return True
        compact = lower.replace("-", "").replace("_", "")
        if len(compact) >= 6 and set(compact) == {"0"}:
            return True
    for value in parsed.query.split("&"):
        key, _, item = value.partition("=")
        compact = item.replace("-", "").replace("_", "")
        if key.lower() in {"configurator_id", "configuratorid", "id"} and len(compact) >= 6 and set(compact) == {"0"}:
            return True
    return False


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
        raw = socket.create_connection((self._pinned_ip, 443), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def fetch_source(
    url: str,
    *,
    approved_hosts: Iterable[str],
    robots_allowed: Callable[[str], bool] | None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_RESPONSE_BYTES,
    resolver=socket.getaddrinfo,
    connection_factory=None,
) -> RetrievalResult:
    """Fetch one approved HTTPS URL without redirects, proxies or DNS re-resolution.

    robots_allowed must be an owner-controlled policy check that returns True only
    when robots.txt and source terms permit this exact URL. It must itself fail closed.
    """
    try:
        host, path = _parse_source_url(url, approved_hosts)
        if _is_placeholder_identifier(url):
            raise RetrievalDenied("source URL contains a placeholder identifier")
        if robots_allowed is None:
            raise RetrievalDenied("robots/terms policy callback is required")
        try:
            permitted = robots_allowed(url)
        except Exception as exc:
            raise RetrievalDenied("robots/terms policy check failed") from exc
        if permitted is not True:
            raise RetrievalDenied("robots/terms policy did not permit this URL")
        if timeout <= 0 or timeout > 30:
            raise RetrievalDenied("timeout must be greater than 0 and at most 30 seconds")
        if max_bytes <= 0 or max_bytes > MAX_RESPONSE_BYTES:
            raise RetrievalDenied("response limit is outside the permitted bound")
        addresses = _resolve_public_addresses(host, resolver=resolver)
        pinned_ip = addresses[0]
        factory = connection_factory or _PinnedHTTPSConnection
        connection = factory(host, pinned_ip, timeout)
        try:
            connection.request("GET", path, headers={
                "Host": host,
                "User-Agent": "CarAutopsy-Research-Bot/1.0",
                "Accept": "text/html, text/plain, application/pdf",
                "Accept-Encoding": "identity",
                "Connection": "close",
            })
            response = connection.getresponse()
            status = response.status
            if 300 <= status < 400:
                return RetrievalResult(url, "rejected", "redirect_not_followed", status_code=status, resolved_ip=pinned_ip)
            if status < 200 or status >= 300:
                return RetrievalResult(url, "rejected", "http_status_not_success", status_code=status, resolved_ip=pinned_ip)
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in ALLOWED_CONTENT_TYPES:
                return RetrievalResult(url, "rejected", "unsupported_content_type", status_code=status, content_type=content_type or None, resolved_ip=pinned_ip)
            declared = response.getheader("Content-Length")
            if declared is not None:
                try:
                    if int(declared) < 0 or int(declared) > max_bytes:
                        return RetrievalResult(url, "rejected", "response_too_large", status_code=status, content_type=content_type, resolved_ip=pinned_ip)
                except ValueError:
                    return RetrievalResult(url, "rejected", "invalid_content_length", status_code=status, content_type=content_type, resolved_ip=pinned_ip)
            chunks = []
            total = 0
            while True:
                chunk = response.read(min(65_536, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    return RetrievalResult(url, "rejected", "response_too_large", status_code=status, content_type=content_type, resolved_ip=pinned_ip)
                chunks.append(chunk)
            return RetrievalResult(
                url, "retrieved_unverified", "http_response_retrieved_but_claim_support_not_verified",
                datetime.now(timezone.utc).isoformat(), status, content_type, b"".join(chunks), pinned_ip,
            )
        finally:
            connection.close()
    except RetrievalDenied as exc:
        return RetrievalResult(url if isinstance(url, str) else "", "rejected", str(exc))
    except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException):
        return RetrievalResult(url if isinstance(url, str) else "", "rejected", "network_or_tls_failure")


def validate_candidate_sources(urls: list[str], **fetch_options) -> list[dict]:
    """Return one safe metadata record per URL; no result implies claim verification."""
    results = []
    for url in urls:
        result = fetch_source(url, **fetch_options)
        results.append(result.safe_record())
    return results
