"""Isolated HTML text parser with hard process resource limits."""
from __future__ import annotations

import json
import sys

MAX_INPUT_BYTES = 2_000_000
MAX_OUTPUT_CHARS = 20_000


def _apply_resource_limits() -> None:
    import resource
    limit = 512 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))


def main() -> int:
    try:
        _apply_resource_limits()
        body = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(body) > MAX_INPUT_BYTES:
            raise ValueError("input_byte_limit")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(body, "lxml")
        for tag in soup.find_all(("script", "style", "template", "noscript", "svg", "canvas", "iframe", "object")):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True).replace("\x00", "").strip()
        if not text or len(text) > MAX_OUTPUT_CHARS:
            raise ValueError("output_character_limit")
        sys.stdout.write(json.dumps({"text": text}, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:
        sys.stderr.write(type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
