"""Isolated PDF parser worker; invoked only by hive_source_extract.py."""
from __future__ import annotations

import io
import json
import sys
import time

MAX_INPUT_BYTES = 2_000_000
MAX_PDF_PAGES = 20
MAX_PAGE_CHARS = 20_000


def _extract_pdf_body(body: bytes, max_pages: int, max_chars: int, timeout_seconds: float, clock=time.monotonic) -> dict:
    """Extract page-labelled text; caller runs this inside a resource-limited process."""
    import pdfplumber

    started = clock()
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        if not pdf.pages:
            raise ValueError("empty_pdf")
        if len(pdf.pages) > max_pages:
            raise ValueError("page_limit")
        chunks = []
        locators = []
        locator_texts = {}
        total = 0
        for index, page in enumerate(pdf.pages, start=1):
            if clock() - started > timeout_seconds:
                raise TimeoutError("parse_timeout")
            page_text = page.extract_text()
            if not isinstance(page_text, str) or not page_text.strip():
                continue
            if len(page_text) > MAX_PAGE_CHARS:
                raise ValueError("page_character_limit")
            total += len(page_text)
            if total > max_chars:
                raise ValueError("document_character_limit")
            locator = f"page:{index}"
            clean_page = page_text.strip()
            locator_texts[locator] = clean_page
            chunks.append(f"[{locator}]\n{clean_page}")
            locators.append(locator)
        text = "\n\n".join(chunks).strip()
        if not text:
            raise ValueError("no_extractable_text")
        if len(text) > max_chars:
            raise ValueError("document_character_limit")
        if clock() - started > timeout_seconds:
            raise TimeoutError("parse_timeout")
        return {"text": text, "locators": locators, "locator_texts": locator_texts}


def _apply_resource_limits() -> None:
    """Set hard per-process virtual-memory and CPU ceilings on POSIX systems."""
    import resource

    memory_limit = 512 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))


def main() -> int:
    try:
        max_pages = int(sys.argv[1])
        max_chars = int(sys.argv[2])
        timeout_seconds = float(sys.argv[3])
        _apply_resource_limits()
        body = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(body) > MAX_INPUT_BYTES:
            raise ValueError("input_byte_limit")
        result = _extract_pdf_body(body, max_pages, max_chars, timeout_seconds)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:
        # Only a fixed exception class is emitted; no document text or raw parser error.
        sys.stderr.write(type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
