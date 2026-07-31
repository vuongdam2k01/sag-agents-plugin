"""Regression test: socket-level network errors (TimeoutError/ConnectionError) during
urlopen must be wrapped as SagApiError, not leaked raw — a real bug encountered
while running selftest S14 on sag.home over Tailscale (a GET during a poll timeout
at the socket layer, not wrapped by urllib into a URLError, crashed the whole process).
"""
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401
from sagctl.restclient import SagApiError, SagClient


class TestNetworkErrorWrapping(unittest.TestCase):
    def setUp(self):
        self.client = SagClient(base_url="http://fake", token="t")

    def test_timeout_error_wrapped_as_sag_api_error(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(SagApiError) as ctx:
                self.client.health()
        self.assertEqual(ctx.exception.status, 0)

    def test_connection_error_wrapped_as_sag_api_error(self):
        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            with self.assertRaises(SagApiError) as ctx:
                self.client.health()
        self.assertEqual(ctx.exception.status, 0)

    def test_raw_text_timeout_error_wrapped(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(SagApiError) as ctx:
                self.client.get_document_parsed("src", "doc")
        self.assertEqual(ctx.exception.status, 0)


if __name__ == "__main__":
    unittest.main()
