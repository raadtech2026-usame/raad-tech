"""JT/T 1078 video-signaling body encode/decode tests (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.2/
§6.3, Tables 6.2/6.4/6.5/6.7/6.8/6.9/6.10/6.11) — spec-verified byte layouts, no hardware needed.
"""

import unittest
from datetime import datetime, timezone

from src.vendors.jt808.commands.video_signaling import (
    LiveVideoControl,
    LiveVideoRequest,
    LiveVideoStatusNotify,
    PlaybackControl,
    PlaybackRequest,
    QueryResourceList,
    ResourceListItem,
    ResourceListReport,
    encode_live_video_control,
    encode_live_video_request,
    encode_live_video_status_notify,
    encode_playback_control,
    encode_playback_request,
    encode_query_resource_list,
    parse_resource_list_report,
)
from src.vendors.jt808.protocol.exceptions import MalformedFrameError


class LiveVideoRequestTests(unittest.TestCase):
    def test_encodes_table_6_2_layout(self) -> None:
        request = LiveVideoRequest(
            server_ip="10.0.0.5",
            tcp_port=7900,
            udp_port=7901,
            logical_channel=1,
            data_type=0,
            stream_type=0,
        )
        body = encode_live_video_request(request)

        ip_bytes = "10.0.0.5".encode("gbk")
        self.assertEqual(body[0], len(ip_bytes))
        self.assertEqual(body[1 : 1 + len(ip_bytes)], ip_bytes)
        offset = 1 + len(ip_bytes)
        self.assertEqual(int.from_bytes(body[offset : offset + 2], "big"), 7900)
        self.assertEqual(int.from_bytes(body[offset + 2 : offset + 4], "big"), 7901)
        self.assertEqual(body[offset + 4], 1)  # logical channel
        self.assertEqual(body[offset + 5], 0)  # data type
        self.assertEqual(body[offset + 6], 0)  # stream type
        self.assertEqual(len(body), offset + 7)

    def test_data_type_and_stream_type_are_positional_not_swapped(self) -> None:
        request = LiveVideoRequest(
            server_ip="1.2.3.4",
            tcp_port=1,
            udp_port=2,
            logical_channel=9,
            data_type=3,  # listen-only
            stream_type=1,  # sub stream
        )
        body = encode_live_video_request(request)
        self.assertEqual(body[-3], 9)
        self.assertEqual(body[-2], 3)
        self.assertEqual(body[-1], 1)


class LiveVideoControlTests(unittest.TestCase):
    def test_encodes_table_6_4_layout(self) -> None:
        control = LiveVideoControl(
            logical_channel=2, control=1, close_av_type=0, switch_stream_type=1
        )
        body = encode_live_video_control(control)
        self.assertEqual(body, bytes([2, 1, 0, 1]))
        self.assertEqual(len(body), 4)

    def test_defaults_match_close_all_main_stream(self) -> None:
        control = LiveVideoControl(logical_channel=1, control=0)
        body = encode_live_video_control(control)
        self.assertEqual(body, bytes([1, 0, 0, 0]))


class LiveVideoStatusNotifyTests(unittest.TestCase):
    def test_encodes_table_6_5_layout(self) -> None:
        notify = LiveVideoStatusNotify(logical_channel=1, packet_loss_rate_percent=12)
        body = encode_live_video_status_notify(notify)
        self.assertEqual(body, bytes([1, 12]))


class QueryResourceListTests(unittest.TestCase):
    def test_encodes_table_6_7_layout_with_no_time_constraint(self) -> None:
        query = QueryResourceList(
            logical_channel=0,
            start_time=None,
            end_time=None,
            alarm_flag_filter=0,
            resource_type=3,
            stream_type=0,
            storage_type=0,
        )
        body = encode_query_resource_list(query)
        self.assertEqual(len(body), 24)
        self.assertEqual(body[0], 0)
        self.assertEqual(body[1:7], b"\x00" * 6)
        self.assertEqual(body[7:13], b"\x00" * 6)
        self.assertEqual(body[13:21], b"\x00" * 8)
        self.assertEqual(body[21], 3)
        self.assertEqual(body[22], 0)
        self.assertEqual(body[23], 0)

    def test_encodes_real_time_window_and_alarm_filter(self) -> None:
        start = datetime(2026, 8, 11, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 11, 1, 0, 0, tzinfo=timezone.utc)
        query = QueryResourceList(
            logical_channel=1,
            start_time=start,
            end_time=end,
            alarm_flag_filter=1,
            resource_type=2,
            stream_type=1,
            storage_type=1,
        )
        body = encode_query_resource_list(query)
        self.assertNotEqual(body[1:7], b"\x00" * 6)
        self.assertNotEqual(body[7:13], b"\x00" * 6)
        self.assertEqual(int.from_bytes(body[13:21], "big"), 1)


class PlaybackRequestTests(unittest.TestCase):
    def test_encodes_table_6_10_layout(self) -> None:
        start = datetime(2026, 8, 11, 8, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 11, 9, 0, 0, tzinfo=timezone.utc)
        request = PlaybackRequest(
            server_ip="10.0.0.5",
            tcp_port=7910,
            udp_port=0,
            logical_channel=1,
            av_type=0,
            stream_type=0,
            storage_type=0,
            playback_mode=0,
            speed_multiplier=0,
            start_time=start,
            end_time=end,
        )
        body = encode_playback_request(request)

        ip_bytes = "10.0.0.5".encode("gbk")
        n = len(ip_bytes)
        self.assertEqual(body[0], n)
        offset = 1 + n
        self.assertEqual(int.from_bytes(body[offset : offset + 2], "big"), 7910)
        self.assertEqual(int.from_bytes(body[offset + 2 : offset + 4], "big"), 0)
        self.assertEqual(body[offset + 4], 1)  # logical channel
        self.assertEqual(body[offset + 5], 0)  # av type
        self.assertEqual(body[offset + 6], 0)  # stream type
        self.assertEqual(body[offset + 7], 0)  # storage type
        self.assertEqual(body[offset + 8], 0)  # playback mode
        self.assertEqual(body[offset + 9], 0)  # speed multiplier
        self.assertEqual(len(body), offset + 10 + 6 + 6)  # + start BCD[6] + end BCD[6]


class PlaybackControlTests(unittest.TestCase):
    def test_encodes_table_6_11_layout_without_seek(self) -> None:
        control = PlaybackControl(av_channel=1, control=0)
        body = encode_playback_control(control)
        self.assertEqual(len(body), 9)
        self.assertEqual(body[0], 1)
        self.assertEqual(body[1], 0)
        self.assertEqual(body[2], 0)
        self.assertEqual(body[3:9], b"\x00" * 6)

    def test_encodes_seek_position_when_dragging(self) -> None:
        seek_at = datetime(2026, 8, 11, 8, 30, 0, tzinfo=timezone.utc)
        control = PlaybackControl(av_channel=1, control=5, seek_position=seek_at)
        body = encode_playback_control(control)
        self.assertNotEqual(body[3:9], b"\x00" * 6)


class ResourceListReportTests(unittest.TestCase):
    def _item_bytes(
        self,
        *,
        channel: int = 1,
        start: datetime,
        end: datetime,
        alarm_flag: int = 0,
        resource_type: int = 2,
        stream_type: int = 0,
        storage_type: int = 0,
        file_size: int = 1024,
    ) -> bytes:
        from src.vendors.jt808.protocol.bcd_datetime import encode_bcd_datetime

        return (
            bytes([channel])
            + encode_bcd_datetime(start)
            + encode_bcd_datetime(end)
            + alarm_flag.to_bytes(8, "big")
            + bytes([resource_type, stream_type, storage_type])
            + file_size.to_bytes(4, "big")
        )

    def test_parses_zero_resource_response(self) -> None:
        body = (5).to_bytes(2, "big") + (0).to_bytes(4, "big")
        report = parse_resource_list_report(body)
        self.assertEqual(report.original_serial_no, 5)
        self.assertEqual(report.total_resource_count, 0)
        self.assertEqual(report.items, ())

    def test_parses_multiple_resource_items(self) -> None:
        start = datetime(2026, 8, 11, 8, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 11, 9, 0, 0, tzinfo=timezone.utc)
        item1 = self._item_bytes(channel=1, start=start, end=end, file_size=2048)
        item2 = self._item_bytes(channel=2, start=start, end=end, file_size=4096)
        body = (7).to_bytes(2, "big") + (2).to_bytes(4, "big") + item1 + item2

        report = parse_resource_list_report(body)

        self.assertEqual(report.original_serial_no, 7)
        self.assertEqual(report.total_resource_count, 2)
        self.assertEqual(len(report.items), 2)
        self.assertEqual(report.items[0].logical_channel, 1)
        self.assertEqual(report.items[0].file_size_bytes, 2048)
        self.assertEqual(report.items[0].start_time, start)
        self.assertEqual(report.items[0].end_time, end)
        self.assertEqual(report.items[1].logical_channel, 2)
        self.assertEqual(report.items[1].file_size_bytes, 4096)

    def test_rejects_body_shorter_than_fixed_header(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_resource_list_report(b"\x00\x01\x00")

    def test_rejects_item_section_not_a_multiple_of_item_length(self) -> None:
        body = (1).to_bytes(2, "big") + (1).to_bytes(4, "big") + b"\x00" * 10
        with self.assertRaises(MalformedFrameError):
            parse_resource_list_report(body)


if __name__ == "__main__":
    unittest.main()
