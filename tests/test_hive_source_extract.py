"""Bounded extraction tests; all documents are synthetic and local."""
import unittest
from unittest.mock import patch

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

    def test_pdf_extracts_bounded_pages_with_page_locators(self):
        fake = FakePdf([FakePage("page one"), FakePage("page two")])
        with patch("pdfplumber.open", return_value=fake):
            result = extract_source_text(b"%PDF-fake", "application/pdf")
        self.assertEqual(result.locators, ("page:1", "page:2"))
        self.assertIn("page two", result.text)

    def test_pdf_page_count_limit(self):
        fake = FakePdf([FakePage("x"), FakePage("y")])
        with patch("pdfplumber.open", return_value=fake):
            with self.assertRaisesRegex(ExtractionRejected, "page limit"):
                extract_source_text(b"%PDF-fake", "application/pdf", max_pages=1)

    def test_pdf_page_character_limit(self):
        fake = FakePdf([FakePage("x" * (MAX_PAGE_CHARS + 1))])
        with patch("pdfplumber.open", return_value=fake):
            with self.assertRaisesRegex(ExtractionRejected, "page character"):
                extract_source_text(b"%PDF-fake", "application/pdf")

    def test_pdf_parse_time_limit(self):
        times = iter([0.0, 6.0])
        fake = FakePdf([FakePage("slow page")])
        with patch("pdfplumber.open", return_value=fake):
            with self.assertRaisesRegex(ExtractionRejected, "time limit"):
                extract_source_text(b"%PDF-fake", "application/pdf", clock=lambda: next(times))

    def test_malformed_pdf_is_rejected(self):
        with patch("pdfplumber.open", side_effect=ValueError("bad pdf")):
            with self.assertRaisesRegex(ExtractionRejected, "malformed"):
                extract_source_text(b"not a pdf", "application/pdf")


if __name__ == "__main__":
    unittest.main()
