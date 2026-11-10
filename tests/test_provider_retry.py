import unittest
from unittest.mock import Mock, patch

import requests

from scripts.provider_retry import (
    GEMINI_TIMEOUT,
    GeminiTransientError,
    generate_content_with_fallback,
    post_gemini_with_retry,
)


class GeminiRetryTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        self.kwargs = {
            "headers": {"Authorization": "Bearer test-key"},
            "json": {"model": "gemini-3.8-flash", "messages": []},
        }

    @patch("scripts.provider_retry.time.sleep")
    @patch("scripts.provider_retry.random.uniform", return_value=0.5)
    @patch("scripts.provider_retry.requests.post")
    def test_retries_503_then_read_timeout_then_success(self, post, _jitter, sleep):
        unavailable = Mock(status_code=503, headers={})
        unavailable.raise_for_status.side_effect = None
        recovered = Mock(status_code=200)
        recovered.raise_for_status.return_value = None
        post.side_effect = [unavailable, requests.exceptions.ReadTimeout("socket timed out"), recovered]

        result = post_gemini_with_retry(self.url, **self.kwargs)

        self.assertIs(result, recovered)
        self.assertEqual(post.call_count, 3)
        self.assertEqual([call.kwargs["timeout"] for call in post.call_args_list],
                         [GEMINI_TIMEOUT] * 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2.5, 4.5])

    @patch("scripts.provider_retry.time.sleep")
    @patch("scripts.provider_retry.random.uniform", return_value=0.5)
    @patch("scripts.provider_retry.requests.post")
    def test_retries_timeout_until_attempt_limit(self, post, _jitter, sleep):
        post.side_effect = requests.exceptions.ReadTimeout("socket timed out")

        with self.assertRaises(requests.exceptions.ReadTimeout):
            post_gemini_with_retry(self.url, **self.kwargs)

        self.assertEqual(post.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    @patch("scripts.provider_retry.time.sleep")
    @patch("scripts.provider_retry.requests.post")
    def test_does_not_retry_fatal_client_error(self, post, sleep):
        response = Mock(status_code=400, headers={})
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("bad request")
        post.return_value = response

        with self.assertRaises(requests.exceptions.HTTPError):
            post_gemini_with_retry(self.url, **self.kwargs)

        post.assert_called_once()
        sleep.assert_not_called()

    @patch("scripts.provider_retry.time.sleep")
    @patch("scripts.provider_retry.requests.post")
    def test_honors_retry_after_header(self, post, sleep):
        unavailable = Mock(status_code=503, headers={"Retry-After": "7"})
        recovered = Mock(status_code=200)
        recovered.raise_for_status.return_value = None
        post.side_effect = [unavailable, recovered]

        self.assertIs(post_gemini_with_retry(self.url, **self.kwargs), recovered)
        sleep.assert_called_once_with(7.0)


class NativeGeminiFallbackTests(unittest.TestCase):
    def setUp(self):
        self.args = {
            "prompt": "Return one word.",
            "api_key": "test-secret",
            "primary_model": "gemini-3.8-flash",
            "fallback_model": "gemini-3.5-flash-lite",
        }

    @patch("scripts.provider_retry.time.sleep")
    @patch("scripts.provider_retry.random.uniform", return_value=0.5)
    @patch("scripts.provider_retry.requests.post")
    def test_falls_back_after_primary_503_retry_exhaustion(self, post, _jitter, sleep):
        unavailable = [Mock(status_code=503, headers={}) for _ in range(4)]
        for response in unavailable:
            response.close.return_value = None
        recovered = Mock(status_code=200)
        recovered.raise_for_status.return_value = None
        recovered.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Fallback "}, {"text": "OK"}]}}]
        }
        post.side_effect = unavailable + [recovered]

        text, model = generate_content_with_fallback(**self.args)

        self.assertEqual(text, "Fallback OK")
        self.assertEqual(model, "gemini-3.5-flash-lite")
        self.assertEqual(post.call_count, 5)
        self.assertEqual(sleep.call_count, 4)
        first_call = post.call_args_list[0]
        self.assertIn("/models/gemini-3.8-flash:generateContent", first_call.args[0])
        self.assertEqual(first_call.kwargs["headers"]["x-goog-api-key"], "test-secret")
        self.assertNotIn("test-secret", first_call.args[0])
        self.assertNotIn("Authorization", first_call.kwargs["headers"])
        self.assertEqual(first_call.kwargs["json"]["contents"][0]["parts"][0]["text"], self.args["prompt"])

    @patch("scripts.provider_retry.time.sleep")
    @patch("scripts.provider_retry.random.uniform", return_value=0.5)
    @patch("scripts.provider_retry.requests.post")
    def test_falls_back_after_primary_read_timeouts(self, post, _jitter, _sleep):
        recovered = Mock(status_code=200)
        recovered.raise_for_status.return_value = None
        recovered.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
        }
        post.side_effect = [requests.exceptions.ReadTimeout("timed out")] * 4 + [recovered]

        text, model = generate_content_with_fallback(**self.args)

        self.assertEqual((text, model), ("ok", "gemini-3.5-flash-lite"))
        self.assertEqual(post.call_count, 5)
        self.assertEqual(post.call_args.kwargs["timeout"], GEMINI_TIMEOUT)

    @patch("scripts.provider_retry.time.sleep")
    @patch("scripts.provider_retry.requests.post")
    def test_does_not_fallback_on_non_transient_400(self, post, sleep):
        response = Mock(status_code=400)
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("bad request")
        post.return_value = response

        with self.assertRaises(requests.exceptions.HTTPError):
            generate_content_with_fallback(**self.args)

        post.assert_called_once()
        sleep.assert_not_called()

    @patch("scripts.provider_retry.time.sleep")
    @patch("scripts.provider_retry.random.uniform", return_value=0.5)
    @patch("scripts.provider_retry.requests.post")
    def test_raises_when_primary_and_fallback_are_unavailable(self, post, _jitter, _sleep):
        post.side_effect = requests.exceptions.ReadTimeout("timed out")

        with self.assertRaises(GeminiTransientError):
            generate_content_with_fallback(**self.args)

        self.assertEqual(post.call_count, 8)


if __name__ == "__main__":
    unittest.main()
