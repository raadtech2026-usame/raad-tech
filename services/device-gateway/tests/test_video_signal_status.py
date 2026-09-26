"""ADR-0046 §1 — camera presence from the terminal's own `0x0200` video-signal-loss item (`0x15`):
the additional-item parser, the publish-on-change tracker, `LocationHandler`'s new event, and the
event's publisher wiring (both publishers, so the ADR-0030 "new event missing from the Redis
publisher" failure cannot repeat)."""

import json
import unittest
from datetime import datetime, timezone

from src.events.device_position_reported import DevicePositionReported
from src.events.device_video_signal_status_reported import DeviceVideoSignalStatusReported
from src.events.publisher_port import LoggingEventPublisher
from src.events.redis_event_publisher import _fields_for
from src.vendors.jt808.dispatcher.handler import HandlerContext
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.vendors.jt808.handlers.location_handler import LocationHandler, VideoSignalStatusTracker
from src.vendors.jt808.handlers.position_additional_info import (
    VideoSignalStatus,
    parse_additional_items,
    video_signal_status,
)
from src.vendors.jt808.protocol.message import InboundMessage

#: A real `0x0200` body from terminal 00000000014482607571 (2026-09-19 capture): cameras on ch1
#: and ch3 only, so item 0x15 = 0x0000000A (ch2, ch4 lost).
REAL_BODY = bytes.fromhex(
    "00000020000c0001001ed86e02b2f255000000000000260919170833"
    "010400000000040200000302000014040000000515040000000a1604000000001702000d"
    "18030000001904000000002504000000002a02000030011f310100520100ad020081"
)
TERMINAL_ID = "00000000014482607571"


def _body_with(loss_mask: int | None, occlusion: int | None = None) -> bytes:
    body = REAL_BODY[:28]
    if loss_mask is not None:
        body += b"\x15\x04" + loss_mask.to_bytes(4, "big")
    if occlusion is not None:
        body += b"\x16\x04" + occlusion.to_bytes(4, "big")
    return body


class AdditionalItemParsingTests(unittest.TestCase):
    def test_the_real_report_says_ch1_and_ch3_have_signal(self) -> None:
        status = video_signal_status(parse_additional_items(REAL_BODY))
        self.assertEqual(status, VideoSignalStatus(loss_mask=0x0A, occlusion_mask=0))
        present = [ch for ch in range(1, 5) if not status.loss_mask & (1 << (ch - 1))]
        self.assertEqual(present, [1, 3])

    def test_a_camera_added_on_ch2_clears_its_bit(self) -> None:
        status = video_signal_status(parse_additional_items(_body_with(0x08)))
        present = [ch for ch in range(1, 5) if not status.loss_mask & (1 << (ch - 1))]
        self.assertEqual(present, [1, 2, 3])

    def test_no_0x15_item_means_no_status(self) -> None:
        self.assertIsNone(video_signal_status(parse_additional_items(REAL_BODY[:28])))

    def test_a_truncated_item_list_keeps_the_items_before_it(self) -> None:
        items = parse_additional_items(_body_with(0x0A) + b"\x16\x04\x00\x00")
        self.assertEqual(items[0x15], b"\x00\x00\x00\x0a")
        self.assertNotIn(0x16, items)

    def test_a_wrong_length_0x15_is_ignored(self) -> None:
        body = REAL_BODY[:28] + b"\x15\x02\x00\x0a"
        self.assertIsNone(video_signal_status(parse_additional_items(body)))


class TrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 0.0
        self.tracker = VideoSignalStatusTracker(refresh_seconds=300, clock=lambda: self.now)
        self.status = VideoSignalStatus(loss_mask=0x0A, occlusion_mask=0)

    def test_first_report_is_published(self) -> None:
        self.assertTrue(self.tracker.should_publish("T", "c1", self.status))

    def test_an_unchanged_report_is_not_republished_until_the_refresh(self) -> None:
        self.tracker.should_publish("T", "c1", self.status)
        self.now = 20
        self.assertFalse(self.tracker.should_publish("T", "c1", self.status))
        self.now = 301
        self.assertTrue(self.tracker.should_publish("T", "c1", self.status))

    def test_a_change_is_published_at_once(self) -> None:
        self.tracker.should_publish("T", "c1", self.status)
        self.assertTrue(
            self.tracker.should_publish("T", "c1", VideoSignalStatus(loss_mask=0x08, occlusion_mask=0))
        )

    def test_a_new_connection_republishes(self) -> None:
        self.tracker.should_publish("T", "c1", self.status)
        self.assertTrue(self.tracker.should_publish("T", "c2", self.status))


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event) -> None:
        self.published.append(event)


def _message(body: bytes) -> InboundMessage:
    return InboundMessage(
        message_id=0x0200,
        terminal_id=TERMINAL_ID,
        serial_no=1,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


class LocationHandlerVideoSignalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        async def noop_close(cid, reason):
            return None

        self.sessions = DeviceSessionManager(registry=DeviceSessionRegistry(), close_connection=noop_close)
        await self.sessions.create(
            connection_id="conn-1",
            terminal_id=TERMINAL_ID,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        self.context = HandlerContext(connection_id="conn-1", device_sessions=self.sessions)
        self.publisher = RecordingPublisher()
        self.handler = LocationHandler(self.publisher)

    def _signal_events(self):
        return [e for e in self.publisher.published if isinstance(e, DeviceVideoSignalStatusReported)]

    async def test_a_real_report_publishes_the_position_and_the_camera_signal(self) -> None:
        await self.handler.handle(_message(REAL_BODY), self.context)
        self.assertEqual(len([e for e in self.publisher.published if isinstance(e, DevicePositionReported)]), 1)
        [event] = self._signal_events()
        self.assertEqual(event.video_signal_loss_mask, 0x0A)
        self.assertEqual((event.device_id, event.organization_id), ("device-1", "org-1"))

    async def test_the_next_identical_report_publishes_only_the_position(self) -> None:
        await self.handler.handle(_message(REAL_BODY), self.context)
        await self.handler.handle(_message(REAL_BODY), self.context)
        self.assertEqual(len(self._signal_events()), 1)

    async def test_a_newly_connected_camera_is_published_at_once(self) -> None:
        await self.handler.handle(_message(_body_with(0x0A)), self.context)
        await self.handler.handle(_message(_body_with(0x08)), self.context)
        self.assertEqual([e.video_signal_loss_mask for e in self._signal_events()], [0x0A, 0x08])

    async def test_a_report_without_the_item_publishes_no_camera_signal(self) -> None:
        await self.handler.handle(_message(REAL_BODY[:28]), self.context)
        self.assertEqual(self._signal_events(), [])


class PublisherWiringTests(unittest.IsolatedAsyncioTestCase):
    def _event(self) -> DeviceVideoSignalStatusReported:
        now = datetime(2026, 9, 26, 5, 0, tzinfo=timezone.utc)
        return DeviceVideoSignalStatusReported(
            terminal_id=TERMINAL_ID,
            organization_id="org-1",
            vehicle_id="vehicle-1",
            device_id="device-1",
            video_signal_loss_mask=0x0A,
            video_signal_occlusion_mask=0,
            event_time=now,
            received_at=now,
        )

    async def test_redis_envelope_carries_the_masks(self) -> None:
        fields = _fields_for(self._event())
        data = json.loads(fields["data"])
        self.assertEqual(data["event_type"], "DeviceVideoSignalStatusReported")
        self.assertEqual(data["payload"]["video_signal_loss_mask"], 10)
        self.assertEqual(data["payload"]["device_id"], "device-1")

    async def test_logging_publisher_accepts_it(self) -> None:
        with self.assertLogs("device_gateway.events.publisher", level="INFO") as logs:
            await LoggingEventPublisher().publish(self._event())
        self.assertIn("device_video_signal_status_reported", logs.output[0])
