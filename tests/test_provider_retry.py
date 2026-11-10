import unittest
from unittest.mock import Mock, patch

import requests

from scripts.provider_retry import GEMINI_TIMEOUT, post_gemini_with_retry


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


if __name__ == "__main__":
    unittest.main()
