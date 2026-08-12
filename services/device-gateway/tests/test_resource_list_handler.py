"""`ResourceListHandler` (`0x1205`) tests — parses the terminal's resource-list report, correlates
it back to the original `0x9205` via `PendingCommandTracker`, and publishes
`DeviceResourceListReported`."""

import unittest
from datetime import datetime, timezone

from src.events.device_resource_list_reported import DeviceResourceListReported
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.dispatcher.handler import HandlerContext
from src.vendors.jt808.handlers.resource_list_handler import ResourceListHandler
from src.vendors.jt808.protocol.bcd_datetime import encode_bcd_datetime
from src.vendors.jt808.protocol.message import InboundMessage
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry

_PHONE = "00000000013800138000"


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


def _resource_item_bytes(
    *, channel: int, start: datetime, end: datetime, file_size: int
) -> bytes:
    return (
        bytes([channel])
        + encode_bcd_datetime(start)
        + encode_bcd_datetime(end)
        + (0).to_bytes(8, "big")
        + bytes([2, 0, 0])  # resource_type=video, stream_type=main, storage_type=main
        + file_size.to_bytes(4, "big")
    )


def _make_message(*, original_serial_no: int, total: int, items: bytes) -> InboundMessage:
    body = original_serial_no.to_bytes(2, "big") + total.to_bytes(4, "big") + items
    return InboundMessage(
        message_id=message_ids.RESOURCE_LIST_REPORT,
        terminal_id=_PHONE,
        serial_no=1,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


async def _noop_close(connection_id: str, reason: str) -> None:
    return None


class ResourceListHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_session_required(self) -> None:
        pending = PendingCommandTracker()
        publisher = RecordingEventPublisher()
        handler = ResourceListHandler(pending, publisher)
        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=_noop_close
        )
        context = HandlerContext(connection_id="conn-1", device_sessions=device_sessions)

        message = _make_message(original_serial_no=1, total=0, items=b"")
        result = await handler.handle(message, context)

        self.assertEqual(publisher.published, [])
        self.assertIsNone(result.response_message_id)

    async def test_correlates_to_the_original_query_and_publishes_the_catalog(self) -> None:
        pending = PendingCommandTracker()
        pending.register(
            terminal_id=_PHONE,
            message_id=message_ids.QUERY_RESOURCE_LIST,
            serial_no=9,
            correlation_id="corr-1",
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
            timeout_seconds=30.0,
        )
        publisher = RecordingEventPublisher()
        handler = ResourceListHandler(pending, publisher)

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

        start = datetime(2026, 8, 11, 8, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 11, 9, 0, 0, tzinfo=timezone.utc)
        item = _resource_item_bytes(channel=1, start=start, end=end, file_size=2048)
        message = _make_message(original_serial_no=9, total=1, items=item)

        result = await handler.handle(message, context)

        self.assertIsNone(result.response_message_id)
        self.assertEqual(len(publisher.published), 1)
        event = publisher.published[0]
        self.assertIsInstance(event, DeviceResourceListReported)
        self.assertEqual(event.correlation_id, "corr-1")
        self.assertEqual(event.total_resource_count, 1)
        self.assertEqual(len(event.items), 1)
        self.assertEqual(event.items[0]["logical_channel"], 1)
        self.assertEqual(event.items[0]["file_size_bytes"], 2048)
        self.assertEqual(event.device_id, "device-1")
        self.assertEqual(len(pending), 0)

    async def test_unmatched_correlation_publishes_with_empty_correlation_id(self) -> None:
        pending = PendingCommandTracker()  # nothing registered
        publisher = RecordingEventPublisher()
        handler = ResourceListHandler(pending, publisher)

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

        message = _make_message(original_serial_no=42, total=0, items=b"")
        await handler.handle(message, context)

        event = publisher.published[0]
        self.assertEqual(event.correlation_id, "")


if __name__ == "__main__":
    unittest.main()
