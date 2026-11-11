"""Bounded text extraction for approved HTML, plain-text and PDF source bodies."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

MAX_INPUT_BYTES = 2_000_000
MAX_PDF_PAGES = 20
MAX_EXTRACTED_CHARS = 60_000
MAX_PAGE_CHARS = 20_000
MAX_PARSE_SECONDS = 5.0
DROP_HTML_TAGS = ("script", "style", "template", "noscript", "svg", "canvas", "iframe", "object")


class ExtractionRejected(ValueError):
    """Raised when a source document cannot be safely extracted within bounds."""


@dataclass(frozen=True)
class ExtractedContent:
    """Transient extracted text and locators; callers decide what evidence to persist."""
    text: str
    locators: tuple[str, ...]
    content_type: str
    locator_texts: dict[str, str]


def _bound_text(text: str, label: str) -> str:
    if not isinstance(text, str):
        raise ExtractionRejected(f"{label} did not produce text")
    cleaned = text.replace("\x00", "")
    if len(cleaned) > MAX_EXTRACTED_CHARS:
        raise ExtractionRejected("extracted text exceeds the document character limit")
    if not cleaned.strip():
        raise ExtractionRejected("source document contains no extractable text")
    return cleaned.strip()


def extract_source_text(
    body: bytes,
    content_type: str,
    *,
    max_input_bytes: int = MAX_INPUT_BYTES,
    max_pages: int = MAX_PDF_PAGES,
    max_chars: int = MAX_EXTRACTED_CHARS,
    parse_timeout_seconds: float = MAX_PARSE_SECONDS,
    clock=time.monotonic,
) -> ExtractedContent:
    """Extract visible text with strict byte/page/character and isolated parser bounds.

    HTML and PDF parsing run in POSIX workers with CPU, address-space, and wall-time
    ceilings. Plain UTF-8 text is decoded in-process because it has no document parser.
    """
    if not isinstance(body, bytes):
        raise ExtractionRejected("source body must be bytes")
    if not isinstance(content_type, str):
        raise ExtractionRejected("content type is missing")
    if max_input_bytes <= 0 or max_input_bytes > MAX_INPUT_BYTES or len(body) > max_input_bytes:
        raise ExtractionRejected("source body exceeds the byte limit")
    if max_pages <= 0 or max_pages > MAX_PDF_PAGES:
        raise ExtractionRejected("page limit is outside the permitted bound")
    if max_chars <= 0 or max_chars > MAX_EXTRACTED_CHARS:
        raise ExtractionRejected("character limit is outside the permitted bound")
    if parse_timeout_seconds <= 0 or parse_timeout_seconds > MAX_PARSE_SECONDS:
        raise ExtractionRejected("parse timeout is outside the permitted bound")

    started = clock()
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type == "text/plain":
        try:
            text = body.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ExtractionRejected("plain-text source is not valid UTF-8") from exc
        result = _bound_text(text, "plain-text extraction")
        if len(result) > max_chars:
            raise ExtractionRejected("extracted text exceeds the configured character limit")
        return ExtractedContent(result, ("document",), normalized_type, {"document": result})

    if normalized_type == "text/html":
        if os.name != "posix":
            raise ExtractionRejected("isolated HTML parsing requires POSIX resource limits")
        worker = Path(__file__).with_name("hive_html_worker.py")
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        try:
            completed = subprocess.run(
                [sys.executable, str(worker)],
                input=body,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=parse_timeout_seconds + 1.5,
                check=False,
                cwd=tempfile.gettempdir(),
                env=environment,
                close_fds=True,
                start_new_session=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExtractionRejected("HTML parsing exceeded the isolated worker time limit") from exc
        except OSError as exc:
            raise ExtractionRejected("isolated HTML worker could not be started") from exc
        if completed.returncode != 0:
            raise ExtractionRejected("isolated HTML worker rejected the document")
        try:
            payload = json.loads(completed.stdout.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExtractionRejected("isolated HTML worker returned malformed output") from exc
        result = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(result, str) or not result.strip() or len(result) > max_chars:
            raise ExtractionRejected("isolated HTML worker output exceeded evidence limits")
        return ExtractedContent(result, ("document",), normalized_type, {"document": result})

    if normalized_type == "application/pdf":
        if os.name != "posix":
            raise ExtractionRejected("isolated PDF parsing requires POSIX resource limits")
        worker = Path(__file__).with_name("hive_pdf_worker.py")
        command = [
            sys.executable, str(worker), str(max_pages), str(max_chars),
            str(parse_timeout_seconds),
        ]
        # Deliberately pass a minimal environment so provider credentials and other
        # application secrets are not inherited by the document parser process.
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        try:
            completed = subprocess.run(
                command,
                input=body,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=parse_timeout_seconds + 1.5,
                check=False,
                cwd=tempfile.gettempdir(),
                env=environment,
                close_fds=True,
                start_new_session=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExtractionRejected("PDF parsing exceeded the isolated worker time limit") from exc
        except OSError as exc:
            raise ExtractionRejected("isolated PDF worker could not be started") from exc
        if completed.returncode != 0:
            raise ExtractionRejected("isolated PDF worker rejected the document")
        try:
            payload = json.loads(completed.stdout.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExtractionRejected("isolated PDF worker returned malformed output") from exc
        text = payload.get("text") if isinstance(payload, dict) else None
        locators = payload.get("locators") if isinstance(payload, dict) else None
        locator_texts = payload.get("locator_texts") if isinstance(payload, dict) else None
        if (
            not isinstance(text, str) or not text.strip() or len(text) > max_chars
            or not isinstance(locators, list)
            or any(not isinstance(locator, str) for locator in locators)
            or not isinstance(locator_texts, dict)
            or set(locator_texts) != set(locators)
            or any(not isinstance(span, str) or not span.strip() for span in locator_texts.values())
        ):
            raise ExtractionRejected("isolated PDF worker output exceeded evidence limits")
        return ExtractedContent(text, tuple(locators), normalized_type, locator_texts)

    raise ExtractionRejected("unsupported source content type")
