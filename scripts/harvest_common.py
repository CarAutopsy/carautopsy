"""Shared, safeguards-compliant helpers for public-source evidence harvesting.

All network access is: credential-free, robots.txt-respecting, rate-limited,
cached only in the system temp directory (never in the repository), and
attributed. A failed or disallowed request is a recorded reason, never a guess.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = (
    "CarAutopsyHarvest/1.0 (+https://github.com/CarAutopsy/carautopsy; "
    "public research; no credentials; rate-limited)"
)
REQUEST_DELAY_SECONDS = 2.0
MAX_ATTEMPTS = 2
TIMEOUT_SECONDS = 60
CACHE_DIR = Path(tempfile.gettempdir()) / "carautopsy-harvest-cache"
_LAST_REQUEST: dict[str, float] = {}
_ROBOTS: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class HarvestError(RuntimeError):
    """Explicit failure for a harvest step; callers record it as a reason."""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def robots_allows(url: str, *, fetch: bool = True) -> bool:
    """Return True only when robots.txt explicitly permits our User-Agent."""
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in _ROBOTS:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        if not fetch:
            _ROBOTS[origin] = None
            return False
        missing = False
        try:
            _throttle(parsed.netloc)
            request = urllib.request.Request(
                f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                content = response.read().decode("utf-8-sig", "replace")
            parser.parse(content.splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                _ROBOTS[origin] = None
                return False
            # No robots.txt published: no restrictions, but still rate-limited.
            missing = True
            parser.parse([])
        except Exception:  # noqa: BLE001 - fail closed on any robots error
            _ROBOTS[origin] = None
            return False
        if not parser.entries and parser.default_entry is None and not missing:
            _ROBOTS[origin] = None
            return False
        _ROBOTS[origin] = parser
    parser = _ROBOTS[origin]
    if parser is None:
        return False
    try:
        return parser.can_fetch(USER_AGENT, url)
    except Exception:  # noqa: BLE001 - fail closed on a parser error
        return False


def _throttle(host: str) -> None:
    last = _LAST_REQUEST.get(host)
    if last is not None:
        wait = REQUEST_DELAY_SECONDS - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _LAST_REQUEST[host] = time.monotonic()


def fetch_url(url: str, *, respect_robots: bool = True) -> dict[str, Any]:
    """GET a public URL with robots/rate-limit enforcement and temp caching.

    Returns a metadata dict. Raw bytes are cached outside the repository only.
    """
    result: dict[str, Any] = {
        "url": url,
        "host": host_of(url),
        "retrieved_at": utc_now(),
        "robots_checked": respect_robots,
        "status": None,
        "content_type": None,
        "bytes": 0,
        "cache_path": None,
        "error": None,
    }
    if respect_robots and not robots_allows(url):
        result["error"] = "robots_disallowed"
        return result
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / hashlib.sha256(url.encode("utf-8")).hexdigest()
    if cache.is_file():
        result.update(status=200, bytes=cache.stat().st_size, cache_path=str(cache))
        return result
    host = host_of(url)
    last_error = "unknown_error"
    for attempt in range(MAX_ATTEMPTS):
        try:
            _throttle(host)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                payload = response.read()
                cache.write_bytes(payload)
                result.update(
                    status=response.status,
                    content_type=response.headers.get("Content-Type"),
                    bytes=len(payload),
                    cache_path=str(cache),
                    error=None,
                )
                return result
        except urllib.error.HTTPError as exc:
            last_error = f"http_{exc.code}"
        except Exception as exc:  # noqa: BLE001 - recorded, never guessed
            last_error = f"{type(exc).__name__}: {str(exc)[:80]}"
        if attempt + 1 < MAX_ATTEMPTS:
            time.sleep(REQUEST_DELAY_SECONDS)
    result["error"] = last_error
    return result


def read_cached_text(meta: dict[str, Any], *, max_bytes: int = 8 * 1024 * 1024) -> str:
    """Decode a cached response; fail closed when missing or oversized."""
    path = meta.get("cache_path")
    if not path or meta.get("error") or not Path(path).is_file():
        raise HarvestError("no cached response available")
    size = Path(path).stat().st_size
    if size > max_bytes:
        raise HarvestError(f"cached response exceeds {max_bytes} bytes")
    return Path(path).read_bytes().decode("utf-8", "replace")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
