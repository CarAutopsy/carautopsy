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



class GeminiTransientError(requests.exceptions.RequestException):
    """Raised after all retries for one Gemini model are exhausted."""


def _generate_content_for_model(prompt, api_key, model, temperature=0.1,
                                max_attempts=4, base_delay=2.0, max_delay=30.0,
                                timeout=GEMINI_TIMEOUT):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if response.status_code in TRANSIENT_HTTP_STATUSES:
                last_error = requests.exceptions.HTTPError(
                    f"Gemini returned transient HTTP {response.status_code}",
                    response=response,
                )
                if attempt == max_attempts:
                    break
                retry_after = _retry_after_seconds(response)
                exponential = min(max_delay, base_delay * (2 ** (attempt - 1)))
                delay = min(max_delay, retry_after) if retry_after is not None else min(
                    max_delay, exponential + random.uniform(0.5, 1.5)
                )
                response.close()
                print(
                    f"gemini ({model}): transient HTTP {response.status_code}; "
                    f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_attempts})."
                )
                time.sleep(delay)
                continue
            response.raise_for_status()
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
            if not text.strip():
                raise ValueError("Gemini returned no text candidate")
            return text
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            exponential = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = min(max_delay, exponential + random.uniform(0.5, 1.5))
            print(
                f"gemini ({model}): {type(exc).__name__}; "
                f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_attempts})."
            )
            time.sleep(delay)
    raise GeminiTransientError(
        f"Gemini model {model} exhausted {max_attempts} attempts: "
        f"{type(last_error).__name__ if last_error else 'unknown transient error'}"
    ) from last_error


def generate_content_with_fallback(prompt, api_key, primary_model, fallback_model,
                                   temperature=0.1, max_attempts=4,
                                   base_delay=2.0, max_delay=30.0,
                                   timeout=GEMINI_TIMEOUT):
    """Call native Gemini GenerateContent; retry primary, then fallback once."""
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured")
    models = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models.append(fallback_model)
    failures = []
    for index, model in enumerate(models):
        try:
            result = _generate_content_for_model(
                prompt, api_key, model, temperature=temperature,
                max_attempts=max_attempts, base_delay=base_delay,
                max_delay=max_delay, timeout=timeout,
            )
            if index:
                print(f"gemini: fallback model {model} succeeded after primary failure")
            return result, model
        except GeminiTransientError as exc:
            failures.append(f"{model}: {exc}")
            if index + 1 < len(models):
                print(f"gemini: primary model exhausted retries; switching to fallback {models[index + 1]}")
    raise GeminiTransientError("All Gemini models failed: " + "; ".join(failures))
