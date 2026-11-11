"""Bounded extraction tests; all documents are synthetic and local."""
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.hive_pdf_worker import _apply_resource_limits, _extract_pdf_body
from scripts.hive_source_extract import (
    ExtractionRejected,
    MAX_PAGE_CHARS,
    extract_source_text,
)


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class HiveSourceExtractionTests(unittest.TestCase):
    def test_plain_text_utf8_and_locator(self):
        result = extract_source_text("Model X 第二代".encode(), "text/plain")
        self.assertIn("第二代", result.text)
        self.assertEqual(result.locators, ("document",))

    def test_plain_text_invalid_utf8_is_rejected(self):
        with self.assertRaisesRegex(ExtractionRejected, "UTF-8"):
            extract_source_text(b"\xff", "text/plain")

    def test_html_removes_script_style_and_embedded_instructions(self):
        body = b"<html><title>Model X</title><body>Power 150 kW<script>steal secrets</script><style>.x{}</style><svg>hidden</svg></body></html>"
        result = extract_source_text(body, "text/html")
        self.assertIn("Model X", result.text)
        self.assertIn("Power 150 kW", result.text)
        self.assertNotIn("steal secrets", result.text)
        self.assertNotIn("hidden", result.text)

    def test_html_malformed_input_is_handled_as_text_when_parseable(self):
        result = extract_source_text(b"<p>Model X", "text/html")
        self.assertIn("Model X", result.text)

    def test_input_byte_and_output_character_limits(self):
        with self.assertRaisesRegex(ExtractionRejected, "byte limit"):
            extract_source_text(b"x" * 20, "text/plain", max_input_bytes=10)
        with self.assertRaisesRegex(ExtractionRejected, "character limit"):
            extract_source_text(b"x" * 20, "text/plain", max_chars=10)

    def test_unsupported_content_type_is_rejected(self):
        with self.assertRaisesRegex(ExtractionRejected, "unsupported"):
            extract_source_text(b"{}", "application/json")

    def test_empty_source_is_rejected(self):
        with self.assertRaises(ExtractionRejected):
            extract_source_text(b"   ", "text/plain")

    def test_pdf_uses_isolated_worker_with_minimal_environment(self):
        payload = {"text": "[page:1]\npage one\n\n[page:2]\npage two", "locators": ["page:1", "page:2"]}
        completed = subprocess.CompletedProcess(
            args=["python"], returncode=0,
            stdout=json.dumps(payload).encode(), stderr=b"",
        )
        with patch("scripts.hive_source_extract.subprocess.run", return_value=completed) as run:
            result = extract_source_text(b"%PDF-fake", "application/pdf")
        self.assertEqual(result.locators, ("page:1", "page:2"))
        self.assertIn("page two", result.text)
        kwargs = run.call_args.kwargs
        self.assertLessEqual(kwargs["timeout"], 6.5)
        self.assertNotIn("QWEN_API_KEY", kwargs["env"])
        self.assertNotIn("DEEPSEEK_API_KEY", kwargs["env"])
        self.assertNotIn("GEMINI_API_KEY", kwargs["env"])
        self.assertTrue(kwargs["start_new_session"])

    def test_pdf_worker_sets_hard_address_space_and_cpu_limits(self):
        import resource
        with patch("resource.setrlimit") as setrlimit:
            _apply_resource_limits()
        setrlimit.assert_any_call(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        setrlimit.assert_any_call(resource.RLIMIT_CPU, (5, 6))

    def test_pdf_worker_timeout_is_fail_closed(self):
        with patch(
            "scripts.hive_source_extract.subprocess.run",
            side_effect=subprocess.TimeoutExpired("pdf-worker", 6.5),
        ):
            with self.assertRaisesRegex(ExtractionRejected, "isolated worker time limit"):
                extract_source_text(b"%PDF-fake", "application/pdf")

    def test_pdf_worker_nonzero_exit_is_fail_closed(self):
        completed = subprocess.CompletedProcess(
            args=["python"], returncode=2, stdout=b"", stderr=b"ValueError",
        )
        with patch("scripts.hive_source_extract.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(ExtractionRejected, "worker rejected"):
                extract_source_text(b"%PDF-fake", "application/pdf")

    def test_caller_cannot_raise_pdf_page_limit(self):
        with self.assertRaisesRegex(ExtractionRejected, "page limit is outside"):
            extract_source_text(b"%PDF-fake", "application/pdf", max_pages=21)

    def test_pdf_page_count_limit_in_worker_parser(self):
        fake = FakePdf([FakePage("x"), FakePage("y")])
        with patch("pdfplumber.open", return_value=fake):
            with self.assertRaisesRegex(ValueError, "page_limit"):
                _extract_pdf_body(b"%PDF-fake", max_pages=1, max_chars=20_000, timeout_seconds=5)

    def test_pdf_page_character_limit_in_worker_parser(self):
        fake = FakePdf([FakePage("x" * (MAX_PAGE_CHARS + 1))])
        with patch("pdfplumber.open", return_value=fake):
            with self.assertRaisesRegex(ValueError, "page_character_limit"):
                _extract_pdf_body(b"%PDF-fake", max_pages=20, max_chars=20_000, timeout_seconds=5)

    def test_pdf_parse_time_limit_in_worker_parser(self):
        times = iter([0.0, 6.0])
        fake = FakePdf([FakePage("slow page")])
        with patch("pdfplumber.open", return_value=fake):
            with self.assertRaisesRegex(TimeoutError, "parse_timeout"):
                _extract_pdf_body(b"%PDF-fake", max_pages=20, max_chars=20_000, timeout_seconds=5, clock=lambda: next(times))

    def test_malformed_pdf_is_rejected_by_worker_parser(self):
        with patch("pdfplumber.open", side_effect=ValueError("bad pdf")):
            with self.assertRaisesRegex(ValueError, "bad pdf"):
                _extract_pdf_body(b"not a pdf", max_pages=20, max_chars=20_000, timeout_seconds=5)


if __name__ == "__main__":
    unittest.main()
