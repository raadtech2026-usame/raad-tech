"""`commands/av_attributes.py` tests — `0x9003` empty-body encode, `0x1003` fixed-10-byte
decode (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.1.1/§6.1.2 Table 6.1, ADR-0030)."""

import unittest

from src.vendors.jt808.commands.av_attributes import (
    encode_query_av_attributes,
    parse_av_attributes_report,
)
from src.vendors.jt808.protocol.exceptions import MalformedFrameError


class EncodeQueryAvAttributesTests(unittest.TestCase):
    def test_body_is_empty(self) -> None:
        self.assertEqual(encode_query_av_attributes(), b"")


class ParseAvAttributesReportTests(unittest.TestCase):
    def _body(self, *, max_audio_channels: int = 1, max_video_channels: int = 4) -> bytes:
        return bytes(
            [
                2,  # input_audio_codec
                1,  # input_audio_channels
                3,  # input_audio_sample_rate
                1,  # input_audio_sample_bits
            ]
        ) + (320).to_bytes(2, "big") + bytes(
            [1, 7, max_audio_channels, max_video_channels]
        )

    def test_parses_every_field_at_the_documented_offset(self) -> None:
        report = parse_av_attributes_report(
            self._body(max_audio_channels=2, max_video_channels=4)
        )

        self.assertEqual(report.input_audio_codec, 2)
        self.assertEqual(report.input_audio_channels, 1)
        self.assertEqual(report.input_audio_sample_rate, 3)
        self.assertEqual(report.input_audio_sample_bits, 1)
        self.assertEqual(report.audio_frame_length, 320)
        self.assertTrue(report.supports_audio_output)
        self.assertEqual(report.video_codec, 7)
        self.assertEqual(report.max_audio_channels, 2)
        self.assertEqual(report.max_video_channels, 4)

    def test_single_channel_terminal(self) -> None:
        report = parse_av_attributes_report(
            self._body(max_audio_channels=1, max_video_channels=1)
        )
        self.assertEqual(report.max_video_channels, 1)

    def test_rejects_a_body_shorter_than_ten_bytes(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_av_attributes_report(b"\x00" * 9)


if __name__ == "__main__":
    unittest.main()
