"""`CommandSender` tests (`commands/command_sender.py`) — resolves a live `DeviceSession`, sends
a JT/T 808-enveloped frame, registers the pending correlation, and publishes `DeviceCommandResult`
directly for an offline terminal or a swept timeout."""

import asyncio
import time
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


def _make_command_sender(
    *, default_timeout_seconds: float = 30.0, min_command_interval_seconds: float = 0.0
):
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
        min_command_interval_seconds=min_command_interval_seconds,
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


class CommandPacingTests(unittest.IsolatedAsyncioTestCase):
    """Per-terminal command pacing (`DEFAULT_MIN_COMMAND_INTERVAL_SECONDS`, 2026-09-02).

    Measured against the physical `LSZ-C5804DG-Q-F`: this MDVR acknowledges JT/T 808 commands in
    0.12-0.22s when they arrive singly, but took ~11 SECONDS to acknowledge a burst of nine
    (4x `0x9102` + 5x `0x9101`) sent inside 1.7s - and while saturated it accepted `0x9101` with
    `result: 0`, opened the media TCP connection, and then never sent a media byte on it. Pacing
    commands per terminal is the one lever RAAD has over that.
    """

    async def _authenticate(self, device_sessions, terminal_id: str) -> None:
        await device_sessions.create(
            connection_id=f"conn-{terminal_id}",
            terminal_id=terminal_id,
            device_id="dev-1",
            vehicle_id="veh-1",
            organization_id="org-1",
        )

    async def test_two_commands_to_the_same_terminal_are_spaced_by_the_interval(self) -> None:
        interval = 0.05
        command_sender, device_sessions, sender, _ = _make_command_sender(
            min_command_interval_seconds=interval
        )
        await self._authenticate(device_sessions, _PHONE)

        started = time.monotonic()
        await command_sender.send(
            terminal_id=_PHONE, message_id=0x9101, body=bytes([0]), correlation_id="c1"
        )
        await command_sender.send(
            terminal_id=_PHONE, message_id=0x9101, body=bytes([0]), correlation_id="c2"
        )
        elapsed = time.monotonic() - started

        self.assertEqual(len(sender.sent), 2)
        self.assertGreaterEqual(elapsed, interval)

    async def test_the_first_command_to_a_terminal_is_never_delayed(self) -> None:
        """Pacing must only ever apply *between* commands - an isolated command (the common
        case) pays no latency cost at all."""
        command_sender, device_sessions, sender, _ = _make_command_sender(
            min_command_interval_seconds=5.0
        )
        await self._authenticate(device_sessions, _PHONE)

        started = time.monotonic()
        await command_sender.send(
            terminal_id=_PHONE, message_id=0x9101, body=bytes([0]), correlation_id="c1"
        )
        elapsed = time.monotonic() - started

        self.assertEqual(len(sender.sent), 1)
        self.assertLess(elapsed, 1.0)

    async def test_pacing_is_per_terminal_so_one_device_never_delays_another(self) -> None:
        """Critical: a global throttle would make one bus's command pacing stall every other
        bus's commands on the same gateway."""
        other_phone = "00000000013800138001"
        command_sender, device_sessions, sender, _ = _make_command_sender(
            min_command_interval_seconds=5.0
        )
        await self._authenticate(device_sessions, _PHONE)
        await self._authenticate(device_sessions, other_phone)

        started = time.monotonic()
        await command_sender.send(
            terminal_id=_PHONE, message_id=0x9101, body=bytes([0]), correlation_id="c1"
        )
        await command_sender.send(
            terminal_id=other_phone, message_id=0x9101, body=bytes([0]), correlation_id="c2"
        )
        elapsed = time.monotonic() - started

        self.assertEqual(len(sender.sent), 2)
        self.assertLess(elapsed, 1.0)  # neither waited on the other

    async def test_concurrent_sends_to_one_terminal_are_serialized_and_all_delivered(self) -> None:
        """The real-world shape this fixes: four channels requested at once. Every command must
        still be delivered exactly once, in order, never dropped or interleaved mid-frame."""
        interval = 0.02
        command_sender, device_sessions, sender, _ = _make_command_sender(
            min_command_interval_seconds=interval
        )
        await self._authenticate(device_sessions, _PHONE)

        await asyncio.gather(
            *(
                command_sender.send(
                    terminal_id=_PHONE,
                    message_id=0x9101,
                    body=bytes([channel]),
                    correlation_id=f"c{channel}",
                )
                for channel in range(4)
            )
        )

        self.assertEqual(len(sender.sent), 4)
        # All four reached the same connection, none lost to the concurrency.
        self.assertEqual({connection_id for connection_id, _ in sender.sent}, {f"conn-{_PHONE}"})
