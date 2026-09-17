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


async def _make_context(
    *, connection_id: str = "conn-1", authenticated_connection_id: str | None = "conn-1"
) -> HandlerContext:
    """A handler context on `connection_id`. The terminal's session is authenticated on
    `authenticated_connection_id` (the same connection by default; `None` for no session at
    all) — since C8 an acknowledgement is only accepted from that connection."""

    async def _noop_close(connection_id: str, reason: str) -> None:
        return None

    device_sessions = DeviceSessionManager(
        registry=DeviceSessionRegistry(), close_connection=_noop_close
    )
    if authenticated_connection_id is not None:
        await device_sessions.create(
            connection_id=authenticated_connection_id,
            terminal_id=_PHONE,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
    return HandlerContext(connection_id=connection_id, device_sessions=device_sessions)


def _pending_9101(serial_no: int = 5) -> PendingCommandTracker:
    pending = PendingCommandTracker()
    pending.register(
        terminal_id=_PHONE,
        message_id=0x9101,
        serial_no=serial_no,
        correlation_id="corr-1",
        device_id="device-1",
        vehicle_id="vehicle-1",
        organization_id="org-1",
        timeout_seconds=30.0,
    )
    return pending


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
        result = await handler.handle(message, await _make_context())

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
        await handler.handle(message, await _make_context())

        event = publisher.published[0]
        self.assertFalse(event.success)
        self.assertEqual(event.reason, "terminal_rejected")

    async def test_unmatched_ack_publishes_nothing_and_does_not_raise(self) -> None:
        pending = PendingCommandTracker()
        publisher = RecordingEventPublisher()
        handler = CommandAckHandler(pending, publisher)

        message = _make_message(original_serial_no=99, original_message_id=0x9101, result=0)
        result = await handler.handle(message, await _make_context())

        self.assertEqual(publisher.published, [])
        self.assertIsNone(result.response_message_id)

    async def test_ack_from_a_connection_with_no_session_is_dropped_and_leaves_the_command_pending(
        self,
    ) -> None:
        """C8 (b): an unauthenticated connection presenting the terminal ID cannot report a
        command's result — and must not consume the pending entry the real device will answer."""
        pending = _pending_9101()
        publisher = RecordingEventPublisher()
        handler = CommandAckHandler(pending, publisher)

        message = _make_message(original_serial_no=5, original_message_id=0x9101, result=0)
        result = await handler.handle(
            message, await _make_context(authenticated_connection_id=None)
        )

        self.assertIsNone(result.response_message_id)
        self.assertEqual(publisher.published, [])
        self.assertEqual(len(pending), 1)

    async def test_ack_from_a_different_connection_than_the_authenticated_one_is_dropped(
        self,
    ) -> None:
        """C8 (d): the terminal is authenticated on `conn-real`; a second socket claiming the same
        terminal ID cannot acknowledge its commands."""
        pending = _pending_9101()
        publisher = RecordingEventPublisher()
        handler = CommandAckHandler(pending, publisher)

        message = _make_message(original_serial_no=5, original_message_id=0x9101, result=0)
        await handler.handle(
            message,
            await _make_context(
                connection_id="conn-impostor", authenticated_connection_id="conn-real"
            ),
        )

        self.assertEqual(publisher.published, [])
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
