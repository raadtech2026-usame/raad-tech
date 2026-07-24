"""LSZ MDVR message parsing tests, against the vendor documents' own worked examples verbatim
(`mdvrdocs/mdvr网络通信协议补充文档180904.docx`'s real packet-capture traces for device `00007`),
the same "test against the primary source's own examples" discipline `tests/test_position_body.py`
already applies to JT/T 808's binary layout.
"""

import unittest
from datetime import datetime, timezone

from src.vendors.lsz_mdvr.protocol.exceptions import MdvrMalformedMessageError
from src.vendors.lsz_mdvr.protocol.parser import parse_frame

_RECEIVED_AT = datetime(2026, 7, 24, tzinfo=timezone.utc)

# Real worked example, device 00007 registering (supplementary doc, packet-capture trace).
# NOTE: the trailing '#' terminator is deliberately omitted from these fixtures — `parse_frame`
# receives frames only via `MdvrFrameBuffer.feed()`, which always strips it before handing a
# frame to the parser (see `framing.py`'s own docstring).
_V101_FRAME = (
    b"$$dc0227,20,V101,00007,,180903 094112,A0010,114,3,341826000,22,40,236220000,0.00,7000,"
    b"000E00010101D383,0000000000000000,0.00,0.00,0.00,0,0.00,67,0|0.00|0|0|0|0|0|0|0,,V1.0.0.1,"
    b"4108,,0,0,0,123,2,,1,1,2,101,,D2017120781,V6.1.45 20160519,"
)

# Real worked example, device 00007 reporting position (supplementary doc, packet-capture trace).
_V114_FRAME = (
    b"$$dc0165,192,V114,00007,,180903 135949,A0010,114,3,338214000,22,40,220920000,0.00,1521000,"
    b"000E00010101D383,0000000000000000,0.00,0.00,0.00,0,0.00,2266,0|0.00|0|0|0|0|0|0|0,1"
)

# Real worked example, device 00007's heartbeat (supplementary doc, packet-capture trace).
_V109_FRAME = b"$$dc0029,13,V109,00007,,180903 110250"


class MdvrParserTests(unittest.TestCase):
    def test_registration_frame_common_header(self) -> None:
        message = parse_frame(_V101_FRAME, received_at=_RECEIVED_AT)
        self.assertEqual(message.keyword, "V101")
        self.assertEqual(message.serial_no, 20)
        self.assertEqual(message.device_serial_number, "00007")
        self.assertIsNone(message.workstation_serial_number)
        self.assertEqual(message.sent_at_raw, "180903 094112")
        self.assertEqual(message.declared_length, 227)
        self.assertEqual(message.received_at, _RECEIVED_AT)

    def test_registration_frame_trailing_fields_include_imei_and_versions(self) -> None:
        message = parse_frame(_V101_FRAME, received_at=_RECEIVED_AT)
        # 18 location-and-status tokens + 1 car-number token precede the protocol-version field.
        trailing = message.fields[19:]
        self.assertEqual(trailing[0], "V1.0.0.1")  # protocol version
        self.assertEqual(trailing[1], "4108")  # device type
        self.assertIn("D2017120781", trailing)  # host version, present somewhere in the tail

    def test_heartbeat_frame_has_no_trailing_fields(self) -> None:
        message = parse_frame(_V109_FRAME, received_at=_RECEIVED_AT)
        self.assertEqual(message.keyword, "V109")
        self.assertEqual(message.device_serial_number, "00007")
        self.assertEqual(message.fields, [])

    def test_position_report_frame_common_header_and_drive_flag(self) -> None:
        message = parse_frame(_V114_FRAME, received_at=_RECEIVED_AT)
        self.assertEqual(message.keyword, "V114")
        self.assertEqual(message.device_serial_number, "00007")
        self.assertEqual(message.sent_at_raw, "180903 135949")
        # 18 location-and-status tokens + 1 drive-flag token.
        self.assertEqual(len(message.fields), 19)
        self.assertEqual(message.fields[-1], "1")

    def test_frame_not_starting_with_marker_raises(self) -> None:
        with self.assertRaises(MdvrMalformedMessageError):
            parse_frame(b"nonsense,1,V101,00007,,180903 094112", received_at=_RECEIVED_AT)

    def test_frame_with_too_few_tokens_raises(self) -> None:
        with self.assertRaises(MdvrMalformedMessageError):
            parse_frame(b"$$dc0010,1,V109", received_at=_RECEIVED_AT)

    def test_empty_keyword_raises(self) -> None:
        with self.assertRaises(MdvrMalformedMessageError):
            parse_frame(b"$$dc0010,1,,00007,,180903 094112", received_at=_RECEIVED_AT)

    def test_empty_device_serial_number_raises(self) -> None:
        with self.assertRaises(MdvrMalformedMessageError):
            parse_frame(b"$$dc0010,1,V109,,,180903 094112", received_at=_RECEIVED_AT)

    def test_non_numeric_declared_length_raises(self) -> None:
        with self.assertRaises(MdvrMalformedMessageError):
            parse_frame(b"$$dcXXXX,1,V109,00007,,180903 094112", received_at=_RECEIVED_AT)


if __name__ == "__main__":
    unittest.main()
