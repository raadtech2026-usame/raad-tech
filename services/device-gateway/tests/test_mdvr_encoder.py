"""Outbound LSZ MDVR frame encoding tests (`protocol/encoder.py`)."""

import unittest
from datetime import datetime, timezone

from src.vendors.lsz.protocol.encoder import build_frame, format_sent_at
from src.vendors.lsz.protocol.parser import parse_frame


class FormatSentAtTests(unittest.TestCase):
    def test_formats_as_yymmdd_hhmmss(self) -> None:
        moment = datetime(2018, 9, 3, 11, 2, 53, tzinfo=timezone.utc)
        self.assertEqual(format_sent_at(moment), "180903 110253")


class BuildFrameTests(unittest.TestCase):
    def test_round_trips_through_the_parser(self) -> None:
        frame = build_frame(
            keyword="C100",
            seq=1,
            device_serial_number="00007",
            workstation_serial_number=None,
            sent_at_raw="180903 110152",
            fields=["V101", "180903 110150", "0", "1", ""],
        )
        # A real device receives the raw wire frame terminated by '#'; the frame buffer strips
        # it before parsing (see test_mdvr_parser.py's own note), so strip it the same way here.
        self.assertTrue(frame.endswith(b"#"))
        message = parse_frame(frame[:-1], received_at=datetime.now(timezone.utc))
        self.assertEqual(message.keyword, "C100")
        self.assertEqual(message.serial_no, 1)
        self.assertEqual(message.device_serial_number, "00007")
        self.assertIsNone(message.workstation_serial_number)
        self.assertEqual(message.sent_at_raw, "180903 110152")
        self.assertEqual(
            message.fields, ["V101", "180903 110150", "0", "1", ""]
        )

    def test_declared_length_matches_encoded_content_byte_length(self) -> None:
        frame = build_frame(
            keyword="C501",
            seq=2,
            device_serial_number="00007",
            workstation_serial_number=None,
            sent_at_raw="180903 110253",
            fields=[],
        )
        text = frame.decode("ascii")
        declared_length = int(text[len("$$dc") : len("$$dc") + 4])
        content_after_length = text[len("$$dc") + 5 : -1]  # skip the length field + its comma
        self.assertEqual(declared_length, len(content_after_length.encode("ascii")))

    def test_empty_workstation_serial_encodes_as_empty_field(self) -> None:
        frame = build_frame(
            keyword="C501",
            seq=3,
            device_serial_number="00007",
            workstation_serial_number=None,
            sent_at_raw="180903 110253",
            fields=[],
        )
        message = parse_frame(frame[:-1], received_at=datetime.now(timezone.utc))
        self.assertIsNone(message.workstation_serial_number)


if __name__ == "__main__":
    unittest.main()
