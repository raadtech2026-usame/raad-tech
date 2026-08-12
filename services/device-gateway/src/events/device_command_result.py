"""`DeviceCommandResult` — the "Result/telemetry direction (device-gateway -> Backend)" half of
ADR-0024 §8's command-downlink coordination: "device-gateway publishes a command-result event
(success/failure of the signaling step) the same way it already publishes `DeviceOnline`/
`DeviceOffline`." Published by `commands/command_sender.py` in exactly two cases — a terminal
general-response (`0x0001`) correlated back to a pending command
(`handlers/command_ack_handler.py`), or the pending command timing out before any response
arrived (`commands/pending_commands.py`'s own sweep) — never for a command that's still
in-flight.

**`correlation_id` is always populated** (`jt808.md` #6: "every platform-issued command must be
traceable back to the requesting use-case and its result") — the one field this event's own
publisher (`redis_event_publisher.py`'s `_envelope`) had never previously needed to set for any
of the other three device-plane events, all of which are device-originated facts with no
originating platform request to correlate back to.

**Generic across every JT/T 808 platform-initiated command family**, not video-signaling-specific
— `message_id` names which command this result is for (`0x9101`/`0x9102`/`0x9205`/`0x9201`/
`0x9202`/`0x9105` this phase; any future platform-initiated command family reuses this same event
shape rather than inventing a per-family result event).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeviceCommandResult:
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    correlation_id: str
    message_id: int  # the JT/T 808 message id the original command was sent as
    success: bool
    reason: str  # "acknowledged" | "device_offline" | "terminal_rejected" | "timed_out"
    event_time: datetime
    received_at: datetime
