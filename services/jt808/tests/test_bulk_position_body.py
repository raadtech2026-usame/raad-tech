"""`parse_bulk_position_report` (Phase 9.6; JT/T 808-2013 §8.49 Table 76/77): item-count-driven
parsing of `0x0704`'s length-prefixed sub-items, each sharing `0x0200`'s fixed 28-byte body
format, plus malformed/truncated-batch rejection.
"""

import unittest

from src.handlers.bulk_position_body import parse_bulk_position_report
from src.protocol.exceptions import MalformedFrameError
from tests.test_position_body import _build_body


class BulkPositionBodyParsingTests(unittest.TestCase):
    def test_zero_items_parses_to_empty_list(self) -> None:
        body = (0).to_bytes(2, "big") + bytes([0])
        report = parse_bulk_position_report(body)
        self.assertEqual(report.items, [])
        self.assertEqual(report.position_data_type, 0)

    def test_single_item_parses_correctly(self) -> None:
        item_body = _build_body(raw_latitude=1_000_000, raw_longitude=2_000_000)
        body = (
            (1).to_bytes(2, "big")
            + bytes([0])
            + len(item_body).to_bytes(2, "big")
            + item_body
        )
        report = parse_bulk_position_report(body)
        self.assertEqual(len(report.items), 1)
        self.assertAlmostEqual(report.items[0].latitude, 1.0)
        self.assertAlmostEqual(report.items[0].longitude, 2.0)

    def test_multiple_items_parse_in_wire_order(self) -> None:
        item_bodies = [
            _build_body(raw_latitude=n * 1_000_000, raw_longitude=n * 1_000_000)
            for n in (1, 2, 3)
        ]
        body = (3).to_bytes(2, "big") + bytes([0])
        for item_body in item_bodies:
            body += len(item_body).to_bytes(2, "big") + item_body

        report = parse_bulk_position_report(body)
        self.assertEqual(len(report.items), 3)
        self.assertEqual([round(item.latitude) for item in report.items], [1, 2, 3])

    def test_position_data_type_normal_batch_is_preserved(self) -> None:
        body = (0).to_bytes(2, "big") + bytes([0])
        self.assertEqual(parse_bulk_position_report(body).position_data_type, 0)

    def test_position_data_type_blind_zone_supplement_is_preserved(self) -> None:
        body = (0).to_bytes(2, "big") + bytes([1])
        self.assertEqual(parse_bulk_position_report(body).position_data_type, 1)

    def test_empty_body_raises_malformed_frame_error(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_bulk_position_report(b"")

    def test_item_count_exceeding_available_bytes_raises(self) -> None:
        body = (5).to_bytes(2, "big") + bytes([0])  # claims 5 items, has none
        with self.assertRaises(MalformedFrameError):
            parse_bulk_position_report(body)

    def test_truncated_item_length_prefix_raises(self) -> None:
        body = (
            (1).to_bytes(2, "big") + bytes([0]) + bytes([0x00])
        )  # only 1 of 2 length bytes
        with self.assertRaises(MalformedFrameError):
            parse_bulk_position_report(body)

    def test_item_declaring_more_bytes_than_present_raises(self) -> None:
        item_body = _build_body()
        body = (
            (1).to_bytes(2, "big")
            + bytes([0])
            + (len(item_body) + 10).to_bytes(
                2, "big"
            )  # declares 10 extra bytes that don't exist
            + item_body
        )
        with self.assertRaises(MalformedFrameError):
            parse_bulk_position_report(body)

    def test_malformed_item_body_propagates_malformed_frame_error(self) -> None:
        short_item = b"\x00" * 10  # too short to be a valid position body
        body = (
            (1).to_bytes(2, "big")
            + bytes([0])
            + len(short_item).to_bytes(2, "big")
            + short_item
        )
        with self.assertRaises(MalformedFrameError):
            parse_bulk_position_report(body)


if __name__ == "__main__":
    unittest.main()
