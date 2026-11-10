"""Bounded retry handling for transient Gemini API failures."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import random
import time

import requests


TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}
GEMINI_TIMEOUT = (10, 90)


def _retry_after_seconds(response):
    """Return a valid Retry-After delay, or None when the header is absent/invalid."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def post_gemini_with_retry(url, *, headers, json, max_attempts=4,
                           base_delay=2.0, max_delay=30.0, timeout=GEMINI_TIMEOUT):
    """POST to Gemini, retrying transient HTTP failures and network timeouts.

    max_attempts includes the first request. Retry delays are exponential with
    jitter, bounded by max_delay; a valid Retry-After header takes precedence.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(1, max_attempts + 1):
        response = None
        try:
            response = requests.post(
                url, headers=headers, json=json, timeout=timeout
            )
            if response.status_code not in TRANSIENT_HTTP_STATUSES:
                response.raise_for_status()
                return response

            if attempt == max_attempts:
                response.raise_for_status()

            retry_after = _retry_after_seconds(response)
            exponential = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = min(max_delay, retry_after) if retry_after is not None else min(
                max_delay, exponential + random.uniform(0.5, 1.5)
            )
            status = response.status_code
            response.close()
            print(
                f"gemini: transient HTTP {status}; retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{max_attempts})."
            )
        except requests.exceptions.Timeout as exc:
            if attempt == max_attempts:
                raise
            exponential = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = min(max_delay, exponential + random.uniform(0.5, 1.5))
            print(
                f"gemini: network timeout ({type(exc).__name__}); "
                f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_attempts})."
            )
        except requests.exceptions.ConnectionError as exc:
            if attempt == max_attempts:
                raise
            exponential = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = min(max_delay, exponential + random.uniform(0.5, 1.5))
            print(
                f"gemini: connection error ({type(exc).__name__}); "
                f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_attempts})."
            )

        time.sleep(delay)

    raise RuntimeError("Gemini request exhausted retries")
