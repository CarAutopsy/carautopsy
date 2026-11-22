"""Bounded One Auto API adapter: redacted probe and enrichment-only access.

No secret value is ever printed, logged, serialized, or stored. The live transport
is only used by the explicit ``--probe`` operator command; all library functions
accept an injected transport so tests never make network calls.

One Auto API is classified as ``enrichment_only`` / ``cross_check_only`` until an
owner documents Austrian market, identification and pricing coverage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sys
import time
from typing import Any, Callable

SECRET_NAME = "ONEAUTOAPI_API_KEY"  # name only; the value is never referenced here
DEFAULT_BASE_URL = "https://api.oneautoapi.com"
PROBE_PATH = "/v1/status"
ENRICHMENT_PATH = "/v1/vehicles"
PROVIDER_ID = "oneautoapi"
PRICE_TIER_CEILING = "enrichment_only"

TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_PROBE_REQUESTS = 1
DEFAULT_TIMEOUT = 5.0

ALLOWED_FIELDS = frozenset({
    "make", "model", "variant", "model_year", "fuel_type", "body_style",
    "power", "engine", "transmission", "dimensions", "weight", "price_candidate",
})

_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_KEY_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|secret|authorization)([\"'\s:=]+)([^\s,;\"'}]+)"
)

Transport = Callable[[str, dict[str, str], float], Any]


class OneAutoError(RuntimeError):
    """Safe, classified adapter failure. Messages never contain a secret value."""

    def __init__(self, code: str, secret: str | None = None) -> None:
        self.code = code
        super().__init__(code)


def redact(text: Any, secret: str | None = None) -> str:
    """Return a log-safe rendering of arbitrary text."""
    value = str(text)
    if secret:
        value = value.replace(secret, "[REDACTED]")
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    value = _KEY_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", value)
    return value


def safe_error(exc: BaseException, secret: str | None = None) -> str:
    """Classify an exception without emitting its (possibly sensitive) body."""
    return f"{type(exc).__name__}: {redact(getattr(exc, 'code', str(exc)), secret)}"


def read_secret(environ: dict[str, str] | None = None) -> str | None:
    """Read the secret only from the environment/secret-store abstraction."""
    source = os.environ if environ is None else environ
    value = source.get(SECRET_NAME)
    return value if isinstance(value, str) and value.strip() else None


def secret_present(environ: dict[str, str] | None = None) -> bool:
    return read_secret(environ) is not None


def _response_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> Any:
    import requests

    return requests.get(url, headers=headers, timeout=timeout)


def _status_class(status_code: int) -> str:
    if status_code in (401, 403):
        return "AUTH_DENIED"
    if status_code == 404:
        return "ENDPOINT_NOT_FOUND"
    if status_code in TRANSIENT_STATUSES:
        return "RETRYABLE_FAILURE"
    if 500 <= status_code <= 599:
        return "PROVIDER_FAILURE"
    if 200 <= status_code <= 299:
        return "PASS"
    return f"HTTP_{status_code}"


class RateLimiter:
    """Deterministic minimum-interval limiter suitable for bounded probes."""

    def __init__(self, min_interval: float = 1.0, *, clock: Callable[[], float] | None = None,
                 sleeper: Callable[[float], None] | None = None) -> None:
        if min_interval < 0:
            raise ValueError("min_interval must be non-negative")
        self.min_interval = min_interval
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self._last: float | None = None

    def acquire(self) -> None:
        now = self.clock()
        if self._last is not None:
            remaining = self.min_interval - (now - self._last)
            if remaining > 0:
                self.sleeper(remaining)
                now = self.clock()
        self._last = now


def backoff_delay(attempt: int, base_delay: float = 0.5, max_delay: float = 8.0) -> float:
    """Exponential backoff with a fixed ceiling (no randomness in tests)."""
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    return float(min(max_delay, base_delay * (2 ** (attempt - 1))))


def connectivity_probe(*, secret: str | None = None, environ: dict[str, str] | None = None,
                       transport: Transport | None = None, timeout: float = DEFAULT_TIMEOUT,
                       endpoint: str | None = None) -> dict[str, Any]:
    """Perform at most one bounded request and return a redacted structured result."""
    key = secret if secret is not None else read_secret(environ)
    endpoint = endpoint or f"{DEFAULT_BASE_URL}{PROBE_PATH}"
    result: dict[str, Any] = {
        "provider": PROVIDER_ID,
        "endpoint": endpoint,
        "secret_present": key is not None,
        "requests": 0,
        "max_requests": MAX_PROBE_REQUESTS,
        "timeout_seconds": timeout,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "price_tier_ceiling": PRICE_TIER_CEILING,
        "austrian_price_verified": False,
    }
    if key is None:
        result.update(status="MISSING_SECRET", http_status=None, response_hash=None,
                      confidence=None, notes="No secret value was read or emitted.")
        return result

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        response = (transport or _default_transport)(endpoint, headers, timeout)
        result["requests"] = 1
        status = int(getattr(response, "status_code", 0))
        result["http_status"] = status
        result["status"] = _status_class(status)
        if result["status"] != "PASS":
            result.update(response_hash=None, confidence=None,
                          notes="Non-success response; no body retained.")
            return result
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("malformed response")
        result["response_hash"] = _response_hash(payload)
        result["confidence"] = "low"
        result["notes"] = (
            "Enrichment/cross-check only. Austrian price coverage is not verified; "
            "no catalog or staging record was written."
        )
    except Exception as exc:  # noqa: BLE001 - classified, redacted, never exposed
        code = getattr(exc, "code", None)
        if "Timeout" in type(exc).__name__:
            result["status"] = "TIMEOUT"
        elif "JSON" in type(exc).__name__ or isinstance(exc, ValueError):
            result["status"] = "MALFORMED_RESPONSE"
        elif code in {"AUTH_DENIED", "ENDPOINT_NOT_FOUND", "RETRYABLE_FAILURE"}:
            result["status"] = str(code)
        else:
            result["status"] = "TRANSPORT_FAILURE"
        result.update(http_status=result.get("http_status"), response_hash=None,
                      confidence=None, notes=safe_error(exc, key))
    return result


def fetch_enrichment(*, secret: str | None = None, environ: dict[str, str] | None = None,
                     transport: Transport | None = None, params: dict[str, Any] | None = None,
                     base_url: str = DEFAULT_BASE_URL, path: str = ENRICHMENT_PATH,
                     max_attempts: int = 3, min_interval: float = 1.0,
                     timeout: float = DEFAULT_TIMEOUT,
                     limiter: RateLimiter | None = None,
                     sleeper: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Return whitelisted enrichment data plus redacted provenance."""
    key = secret if secret is not None else read_secret(environ)
    if key is None:
        raise OneAutoError("MISSING_SECRET")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    limiter = limiter or RateLimiter(min_interval, sleeper=sleeper)
    sleep = sleeper or time.sleep
    safe_params = {k: v for k, v in (params or {}).items() if k in ALLOWED_FIELDS}
    endpoint = f"{base_url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    for attempt in range(1, max_attempts + 1):
        limiter.acquire()
        try:
            response = (transport or _default_transport)(endpoint, headers, timeout)
            status = int(getattr(response, "status_code", 0))
            if status == 401 or status == 403:
                raise OneAutoError("AUTH_DENIED")
            if status == 404:
                raise OneAutoError("ENDPOINT_NOT_FOUND")
            if status in TRANSIENT_STATUSES or status >= 500:
                if attempt == max_attempts:
                    raise OneAutoError("RETRYABLE_FAILURE")
                sleep(backoff_delay(attempt))
                continue
            payload = response.json()
            if not isinstance(payload, dict):
                raise OneAutoError("MALFORMED_RESPONSE")
            data = {k: v for k, v in payload.items() if k in ALLOWED_FIELDS}
            if not data:
                raise OneAutoError("MISSING_FIELDS")
            return {
                "data": data,
                "provenance": {
                    "provider": PROVIDER_ID,
                    "endpoint": endpoint,
                    "request_parameters": redact(json.dumps(safe_params, sort_keys=True), key),
                    "response_hash": _response_hash(data),
                    "response_timestamp": datetime.now(timezone.utc).isoformat(),
                    "source_url": endpoint,
                    "confidence": "low",
                    "retrieval_date": datetime.now(timezone.utc).date().isoformat(),
                    "licence_or_terms": "to_be_verified",
                },
                "price_tier_ceiling": PRICE_TIER_CEILING,
                "austrian_price_verified": False,
                "review_required": True,
                "requests": attempt,
            }
        except OneAutoError:
            raise
        except (ValueError, json.JSONDecodeError):
            raise OneAutoError("MALFORMED_RESPONSE") from None
        except Exception as exc:  # noqa: BLE001 - classified, redacted
            if "Timeout" in type(exc).__name__:
                if attempt == max_attempts:
                    raise OneAutoError("TIMEOUT") from None
                sleep(backoff_delay(attempt))
                continue
            raise OneAutoError("TRANSPORT_FAILURE") from None
    raise OneAutoError("RETRYABLE_FAILURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="run one redacted connectivity probe")
    args = parser.parse_args(argv)
    if not args.probe:
        parser.error("specify --probe")
    print(json.dumps(connectivity_probe(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
