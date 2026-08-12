"""`CommandAckHandler` (`0x0001`) tests — correlates a terminal's general-response ack back to a
pending platform-initiated command and publishes `DeviceCommandResult`."""

import unittest
from datetime import datetime, timezone

from src.events.device_command_result import DeviceCommandResult
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.dispatcher.handler import HandlerContext
from src.vendors.jt808.handlers.command_ack_handler import CommandAckHandler
from src.vendors.jt808.protocol.message import InboundMessage
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry

_PHONE = "00000000013800138000"


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


def _make_message(*, original_serial_no: int, original_message_id: int, result: int) -> InboundMessage:
    body = (
        original_serial_no.to_bytes(2, "big")
        + original_message_id.to_bytes(2, "big")
        + bytes([result])
    )
    return InboundMessage(
        message_id=0x0001,
        terminal_id=_PHONE,
        serial_no=1,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


def _make_context() -> HandlerContext:
    async def _noop_close(connection_id: str, reason: str) -> None:
        return None

    device_sessions = DeviceSessionManager(
        registry=DeviceSessionRegistry(), close_connection=_noop_close
    )
    return HandlerContext(connection_id="conn-1", device_sessions=device_sessions)


class CommandAckHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_matched_success_ack_publishes_a_successful_command_result(self) -> None:
        pending = PendingCommandTracker()
        pending.register(
            terminal_id=_PHONE,
            message_id=0x9101,
            serial_no=5,
            correlation_id="corr-1",
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
            timeout_seconds=30.0,
        )
        publisher = RecordingEventPublisher()
        handler = CommandAckHandler(pending, publisher)

        message = _make_message(original_serial_no=5, original_message_id=0x9101, result=0)
        result = await handler.handle(message, _make_context())

        self.assertIsNone(result.response_message_id)
        self.assertEqual(len(publisher.published), 1)
        event = publisher.published[0]
        self.assertIsInstance(event, DeviceCommandResult)
        self.assertTrue(event.success)
        self.assertEqual(event.reason, "acknowledged")
        self.assertEqual(event.correlation_id, "corr-1")
        self.assertEqual(len(pending), 0)  # resolved entry is consumed

    async def test_matched_failure_ack_publishes_terminal_rejected(self) -> None:
        pending = PendingCommandTracker()
        pending.register(
            terminal_id=_PHONE,
            message_id=0x9201,
            serial_no=2,
            correlation_id="corr-2",
            device_id=None,
            vehicle_id=None,
            organization_id=None,
            timeout_seconds=30.0,
        )
        publisher = RecordingEventPublisher()
        handler = CommandAckHandler(pending, publisher)

        message = _make_message(original_serial_no=2, original_message_id=0x9201, result=1)
        await handler.handle(message, _make_context())

        event = publisher.published[0]
        self.assertFalse(event.success)
        self.assertEqual(event.reason, "terminal_rejected")

    async def test_unmatched_ack_publishes_nothing_and_does_not_raise(self) -> None:
        pending = PendingCommandTracker()
        publisher = RecordingEventPublisher()
        handler = CommandAckHandler(pending, publisher)

        message = _make_message(original_serial_no=99, original_message_id=0x9101, result=0)
        result = await handler.handle(message, _make_context())

        self.assertEqual(publisher.published, [])
        self.assertIsNone(result.response_message_id)


if __name__ == "__main__":
    unittest.main()
