"""`POST /video/live` request schema (ADR-0043). The unit tests elsewhere call application services
directly and never build a request model, so the schema's own default and validation are covered
here (the `test_school_erp_api_schemas.py` pattern)."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from raad.modules.video.api.schemas import RequestLiveVideoRequest


class RequestLiveVideoRequestTests(unittest.TestCase):
    def test_documented_body_without_stream_type_defaults_to_main(self) -> None:
        body = RequestLiveVideoRequest(device_id="d-1", camera_id="c-1")
        self.assertEqual(body.stream_type, "main")

    def test_sub_stream_is_accepted(self) -> None:
        body = RequestLiveVideoRequest(device_id="d-1", camera_id="c-1", stream_type="sub")
        self.assertEqual(body.stream_type, "sub")

    def test_unknown_stream_type_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RequestLiveVideoRequest(device_id="d-1", camera_id="c-1", stream_type="hd")

    def test_raw_protocol_integer_is_rejected(self) -> None:
        """The API speaks `main`/`sub`; the JT/T 1078 wire values stay inside the adapter."""
        with self.assertRaises(ValidationError):
            RequestLiveVideoRequest(device_id="d-1", camera_id="c-1", stream_type=1)


if __name__ == "__main__":
    unittest.main()
