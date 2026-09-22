"""`POST /video/live` request schema (ADR-0043). The unit tests elsewhere call application services
directly and never build a request model, so the schema's own default and validation are covered
here (the `test_school_erp_api_schemas.py` pattern)."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from raad.modules.video.api.schemas import (
    PlaybackControlRequest,
    RecordingSearchResponse,
    RequestLiveVideoRequest,
)


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


class PlaybackControlRequestTests(unittest.TestCase):
    """ADR-0044 §4. The API speaks named actions; the `0x9202` control byte is the router's
    own translation, so a client can never name a control this contract doesn't offer."""

    def test_speed_defaults_to_real_time(self) -> None:
        self.assertEqual(PlaybackControlRequest(action="pause").speed, 1)

    def test_every_named_action_is_accepted(self) -> None:
        for action in ("resume", "pause", "fast_forward", "rewind", "seek", "keyframe_only"):
            with self.subTest(action=action):
                self.assertEqual(PlaybackControlRequest(action=action).action, action)

    def test_stop_is_not_an_action_here(self) -> None:
        """`POST /video/sessions/{id}/stop` is the single teardown path — accepting `stop`
        here would let a session be stopped at the device while still open in RAAD."""
        with self.assertRaises(ValidationError):
            PlaybackControlRequest(action="stop")

    def test_raw_protocol_control_byte_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            PlaybackControlRequest(action=1)

    def test_speed_outside_the_specs_own_range_is_rejected(self) -> None:
        """Table 6.11 defines 1..5 (1x/2x/4x/8x/16x); anything else is not a slower or faster
        stream, it is an undefined byte on the wire."""
        for speed in (0, 6, -1):
            with self.subTest(speed=speed):
                with self.assertRaises(ValidationError):
                    PlaybackControlRequest(action="fast_forward", speed=speed)


class RecordingSearchResponseTests(unittest.TestCase):
    def test_pending_carries_no_segments(self) -> None:
        body = RecordingSearchResponse(search_id="s-1", device_id="d-1", status="pending")
        self.assertIsNone(body.segments)

    def test_an_empty_ready_answer_is_not_the_same_as_pending(self) -> None:
        """`[]` means the device holds nothing for that window; `null` means it has not
        answered yet — an operator polling must be able to tell those apart."""
        body = RecordingSearchResponse(
            search_id="s-1", device_id="d-1", status="ready", segments=[]
        )
        self.assertEqual(body.segments, [])
        self.assertIsNotNone(body.segments)

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            RecordingSearchResponse(search_id="s-1", device_id="d-1", status="failed")


if __name__ == "__main__":
    unittest.main()
