"""`CommandSender` tests (`commands/command_sender.py`) — resolves a live `DeviceSession`, sends
a JT/T 808-enveloped frame, registers the pending correlation, and publishes `DeviceCommandResult`
directly for an offline terminal or a swept timeout."""

import asyncio
import unittest
from datetime import datetime, timezone

from src.events.device_command_result import DeviceCommandResult
from src.vendors.jt808.commands.command_sender import CommandSender
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.dispatcher.dispatcher import OutboundSerialCounter
from src.vendors.jt808.protocol.parser import PacketParser
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry

_PHONE = "00000000013800138000"


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []

    async def __call__(self, connection_id: str, frame: bytes) -> None:
        self.sent.append((connection_id, frame))


async def _noop_close(connection_id: str, reason: str) -> None:
    return None


def _make_command_sender(*, default_timeout_seconds: float = 30.0):
    device_sessions = DeviceSessionManager(
        registry=DeviceSessionRegistry(), close_connection=_noop_close
    )
    sender = RecordingSender()
    publisher = RecordingEventPublisher()
    command_sender = CommandSender(
        device_sessions=device_sessions,
        send=sender,
        serial_counter=OutboundSerialCounter(),
        pending=PendingCommandTracker(),
        event_publisher=publisher,
        default_timeout_seconds=default_timeout_seconds,
    )
    return command_sender, device_sessions, sender, publisher


class CommandSenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_to_an_offline_terminal_publishes_failure_and_returns_false(
        self,
    ) -> None:
        command_sender, _, sender, publisher = _make_command_sender()

        sent = await command_sender.send(
            terminal_id=_PHONE, message_id=0x9101, body=b"\x00", correlation_id="corr-1"
        )

        self.assertFalse(sent)
        self.assertEqual(sender.sent, [])
        self.assertEqual(len(publisher.published), 1)
        result = publisher.published[0]
        self.assertIsInstance(result, DeviceCommandResult)
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "device_offline")
        self.assertEqual(result.correlation_id, "corr-1")

    async def test_send_to_an_authenticated_terminal_builds_a_real_frame_and_registers_pending(
        self,
    ) -> None:
        command_sender, device_sessions, sender, publisher = _make_command_sender()
        await device_sessions.create(
            connection_id="conn-1",
            terminal_id=_PHONE,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )

        sent = await command_sender.send(
            terminal_id=_PHONE, message_id=0x9101, body=b"\xaa\xbb", correlation_id="corr-2"
        )

        self.assertTrue(sent)
        self.assertEqual(len(sender.sent), 1)
        connection_id, frame = sender.sent[0]
        self.assertEqual(connection_id, "conn-1")
        self.assertEqual(publisher.published, [])  # not yet acked or timed out

        message = PacketParser().parse(frame[1:-1], received_at=datetime.now(timezone.utc))
        self.assertEqual(message.message_id, 0x9101)
        self.assertEqual(message.terminal_id, _PHONE)
        self.assertEqual(message.body, b"\xaa\xbb")

    async def test_sweep_timeouts_publishes_failure_for_expired_pending_commands(
        self,
    ) -> None:
        command_sender, device_sessions, _sender, publisher = _make_command_sender(
            default_timeout_seconds=0.01
        )
        await device_sessions.create(
            connection_id="conn-1",
            terminal_id=_PHONE,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        await command_sender.send(
            terminal_id=_PHONE, message_id=0x9101, body=b"\x00", correlation_id="corr-3"
        )
        self.assertEqual(publisher.published, [])

        await asyncio.sleep(0.05)
        await command_sender.sweep_timeouts()

        self.assertEqual(len(publisher.published), 1)
        result = publisher.published[0]
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "timed_out")
        self.assertEqual(result.correlation_id, "corr-3")


if __name__ == "__main__":
    unittest.main()
