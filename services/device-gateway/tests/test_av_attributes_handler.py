"""`AvAttributesHandler` (`0x1003`) tests — parses the terminal's A/V attributes report,
correlates it back to the original `0x9003` via `PendingCommandTracker.
resolve_by_terminal_and_message` (no serial-number echo in this reply, unlike `0x1205`), and
publishes `DeviceAvAttributesReported`."""

import unittest
from datetime import datetime, timezone

from src.events.device_av_attributes_reported import DeviceAvAttributesReported
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.dispatcher.handler import HandlerContext
from src.vendors.jt808.handlers.av_attributes_handler import AvAttributesHandler
from src.vendors.jt808.protocol.message import InboundMessage
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry

_PHONE = "00000000013800138000"


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


def _report_body(*, max_audio_channels: int, max_video_channels: int) -> bytes:
    return bytes(
        [
            0,  # input_audio_codec
            1,  # input_audio_channels
            0,  # input_audio_sample_rate
            1,  # input_audio_sample_bits
        ]
    ) + (160).to_bytes(2, "big") + bytes(
        [
            1,  # supports_audio_output
            99,  # video_codec
            max_audio_channels,
            max_video_channels,
        ]
    )


def _make_message(*, body: bytes) -> InboundMessage:
    return InboundMessage(
        message_id=message_ids.AV_ATTRIBUTES_REPORT,
        terminal_id=_PHONE,
        serial_no=1,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


async def _noop_close(connection_id: str, reason: str) -> None:
    return None


class AvAttributesHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_session_required(self) -> None:
        pending = PendingCommandTracker()
        publisher = RecordingEventPublisher()
        handler = AvAttributesHandler(pending, publisher)
        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=_noop_close
        )
        context = HandlerContext(connection_id="conn-1", device_sessions=device_sessions)

        message = _make_message(body=_report_body(max_audio_channels=1, max_video_channels=4))
        result = await handler.handle(message, context)

        self.assertEqual(publisher.published, [])
        self.assertIsNone(result.response_message_id)

    async def test_correlates_to_the_original_query_and_publishes_channel_count(self) -> None:
        pending = PendingCommandTracker()
        pending.register(
            terminal_id=_PHONE,
            message_id=message_ids.QUERY_AV_ATTRIBUTES,
            serial_no=7,
            correlation_id="corr-1",
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
            timeout_seconds=30.0,
        )
        publisher = RecordingEventPublisher()
        handler = AvAttributesHandler(pending, publisher)

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=_noop_close
        )
        await device_sessions.create(
            connection_id="conn-1",
            terminal_id=_PHONE,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        context = HandlerContext(connection_id="conn-1", device_sessions=device_sessions)

        message = _make_message(body=_report_body(max_audio_channels=2, max_video_channels=4))
        result = await handler.handle(message, context)

        self.assertIsNone(result.response_message_id)
        self.assertEqual(len(publisher.published), 1)
        event = publisher.published[0]
        self.assertIsInstance(event, DeviceAvAttributesReported)
        self.assertEqual(event.correlation_id, "corr-1")
        self.assertEqual(event.max_video_channels, 4)
        self.assertEqual(event.max_audio_channels, 2)
        self.assertEqual(event.device_id, "device-1")
        # resolve_by_terminal_and_message pops the entry regardless of serial_no match.
        self.assertEqual(len(pending), 0)

    async def test_unmatched_correlation_publishes_with_empty_correlation_id(self) -> None:
        pending = PendingCommandTracker()  # nothing registered
        publisher = RecordingEventPublisher()
        handler = AvAttributesHandler(pending, publisher)

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=_noop_close
        )
        await device_sessions.create(
            connection_id="conn-1",
            terminal_id=_PHONE,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        context = HandlerContext(connection_id="conn-1", device_sessions=device_sessions)

        message = _make_message(body=_report_body(max_audio_channels=1, max_video_channels=1))
        await handler.handle(message, context)

        event = publisher.published[0]
        self.assertEqual(event.correlation_id, "")


if __name__ == "__main__":
    unittest.main()
