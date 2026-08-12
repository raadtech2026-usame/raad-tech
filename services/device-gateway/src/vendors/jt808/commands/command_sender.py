"""`CommandSender` — the outbound half of platform-initiated command downlink (ADR-0024 §8's
"device-gateway's `vendors/jt808/` adapter... forwards the message as-is on the GPS/signaling
connection it already holds open for that device, using the same JT808 envelope/serial-number/
response machinery it already uses for every other outbound command"). Resolves the target
terminal's live `DeviceSession` (`session.device_session_manager.DeviceSessionManager.resolve`)
to a `connection_id`, builds a standard JT/T 808 frame (`protocol/encoder.build_frame` — the
*same* encoder every automatic dispatcher response already uses, sharing its
`OutboundSerialCounter` instance, see that class's own docstring), sends it, and registers the
`(terminal_id, message_id, serial_no)` triple with `PendingCommandTracker` so a later `0x0001`
can be correlated back to this exact send (`handlers/command_ack_handler.py`).

**A command to an offline/never-authenticated terminal fails immediately, not silently** — no
`DeviceSession` means no connection to send on; `send()` publishes a `DeviceCommandResult
(success=False, reason="device_offline")` itself in that case and returns `False`, so a caller
(`commands/redis_video_signaling_consumer.py`) never needs its own separate "was this even
deliverable" check.

**Generic across every command family** — this class knows nothing about JT/T 1078 specifically;
`commands/video_signaling.py`'s encoders are its first real caller, not something it depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable

from src.events.device_command_result import DeviceCommandResult
from src.events.publisher_port import EventPublisher
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.dispatcher.dispatcher import OutboundSerialCounter
from src.vendors.jt808.protocol.encoder import build_frame
from src.session.device_session_manager import DeviceSessionManager

SendFrame = Callable[[str, bytes], Awaitable[None]]

DEFAULT_COMMAND_TIMEOUT_SECONDS = 15.0


class CommandSender:
    def __init__(
        self,
        *,
        device_sessions: DeviceSessionManager,
        send: SendFrame,
        serial_counter: OutboundSerialCounter,
        pending: PendingCommandTracker,
        event_publisher: EventPublisher,
        default_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self._device_sessions = device_sessions
        self._send = send
        self._serial_counter = serial_counter
        self._pending = pending
        self._event_publisher = event_publisher
        self._default_timeout_seconds = default_timeout_seconds

    async def send(
        self,
        *,
        terminal_id: str,
        message_id: int,
        body: bytes,
        correlation_id: str,
        timeout_seconds: float | None = None,
    ) -> bool:
        session = self._device_sessions.resolve(terminal_id)
        if session is None:
            await self._publish_result(
                terminal_id=terminal_id,
                organization_id=None,
                vehicle_id=None,
                device_id=None,
                correlation_id=correlation_id,
                message_id=message_id,
                success=False,
                reason="device_offline",
            )
            return False

        serial_no = self._serial_counter.next()
        frame = build_frame(
            message_id=message_id,
            terminal_phone=terminal_id,
            serial_no=serial_no,
            body=body,
        )
        self._pending.register(
            terminal_id=terminal_id,
            message_id=message_id,
            serial_no=serial_no,
            correlation_id=correlation_id,
            device_id=session.device_id,
            vehicle_id=session.vehicle_id,
            organization_id=session.organization_id,
            timeout_seconds=timeout_seconds or self._default_timeout_seconds,
        )
        await self._send(session.connection_id, frame)
        return True

    async def sweep_timeouts(self) -> None:
        for expired in self._pending.sweep_expired():
            await self._publish_result(
                terminal_id=expired.terminal_id,
                organization_id=expired.organization_id,
                vehicle_id=expired.vehicle_id,
                device_id=expired.device_id,
                correlation_id=expired.correlation_id,
                message_id=expired.message_id,
                success=False,
                reason="timed_out",
            )

    async def _publish_result(
        self,
        *,
        terminal_id: str,
        organization_id: str | None,
        vehicle_id: str | None,
        device_id: str | None,
        correlation_id: str,
        message_id: int,
        success: bool,
        reason: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        await self._event_publisher.publish(
            DeviceCommandResult(
                terminal_id=terminal_id,
                organization_id=organization_id,
                vehicle_id=vehicle_id,
                device_id=device_id,
                correlation_id=correlation_id,
                message_id=message_id,
                success=success,
                reason=reason,
                event_time=now,
                received_at=now,
            )
        )
