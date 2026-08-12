"""`PendingCommandTracker` — the correlation half of `jt808.md` #6's "command downlink is
correlation-ID tracked: every platform-issued command must be traceable back to the requesting
use-case and its result." Keyed by `(terminal_id, message_id, serial_no)` — the exact triple a
terminal's own `0x0001` general-response echoes back (`handlers/terminal_general_response_body.
py`), so `handlers/command_ack_handler.py` can resolve which pending command a given ack
actually answers.

**Bounded, not indefinite** (ADR-0024 §16: "the relay's own allocation times out (a bounded
wait, not indefinite)" — the identical discipline applied here to command acknowledgement, not
media-channel allocation): `sweep_expired()` returns every entry whose `sent_at` is older than
its own `timeout_seconds`, removing it from the tracker so a device that never acks (offline,
firmware bug, network drop) cannot grow this map without bound. The caller (`command_sender.py`'s
own background sweep, wired in `Jt808Server`) is responsible for publishing a `DeviceCommandResult
(success=False, reason="timed_out")` for each expired entry.

**Generic across every command family**, not video-signaling-specific — see
`events/device_command_result.py`'s own docstring for why.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class PendingCommand:
    terminal_id: str
    message_id: int
    serial_no: int
    correlation_id: str
    device_id: str | None
    vehicle_id: str | None
    organization_id: str | None
    sent_at: float  # time.monotonic()
    timeout_seconds: float


class PendingCommandTracker:
    def __init__(self) -> None:
        self._pending: dict[tuple[str, int, int], PendingCommand] = {}

    def register(
        self,
        *,
        terminal_id: str,
        message_id: int,
        serial_no: int,
        correlation_id: str,
        device_id: str | None,
        vehicle_id: str | None,
        organization_id: str | None,
        timeout_seconds: float,
    ) -> None:
        key = (terminal_id, message_id, serial_no)
        self._pending[key] = PendingCommand(
            terminal_id=terminal_id,
            message_id=message_id,
            serial_no=serial_no,
            correlation_id=correlation_id,
            device_id=device_id,
            vehicle_id=vehicle_id,
            organization_id=organization_id,
            sent_at=time.monotonic(),
            timeout_seconds=timeout_seconds,
        )

    def resolve(
        self, *, terminal_id: str, message_id: int, serial_no: int
    ) -> PendingCommand | None:
        """Pops and returns the matching pending command, or `None` if nothing is pending for
        this triple (a `0x0001` for a command this tracker never sent, or one that already timed
        out — both expected, not errors; see `handlers/command_ack_handler.py`)."""
        return self._pending.pop((terminal_id, message_id, serial_no), None)

    def sweep_expired(self) -> list[PendingCommand]:
        now = time.monotonic()
        expired_keys = [
            key
            for key, command in self._pending.items()
            if now - command.sent_at > command.timeout_seconds
        ]
        expired = [self._pending.pop(key) for key in expired_keys]
        return expired

    def __len__(self) -> int:
        return len(self._pending)
