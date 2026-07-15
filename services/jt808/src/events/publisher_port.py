"""`EventPublisher` — the port position handlers use to hand off a `DevicePositionReported`
event, instead of ever calling into `tracking` (or any other business module) directly (Phase
9.6; see `device_position_reported.py`'s module docstring for the full architecture rationale).

**No broker technology is approved anywhere in this repository yet** (`.claude/rules/
workflow.md` #1/#2: new dependencies need explicit approval before installation; none has been
proposed or approved for a message broker in any prior phase). JT808 Technical Design §22
(ADR-808-2) calls for a local durable outbox relaying to a broker, mirroring the Business API's
own outbox pattern (Backend LLD §10.1) — but building that durability layer needs a chosen
broker client, which is a dependency decision outside this phase's scope (confirmed with the
user: this phase defines the port and a minimal non-durable default only; a later phase wires a
real outbox + broker implementation behind the same port, with zero change to any handler).

`LoggingEventPublisher` is that minimal default — publishing degrades to a structured log line,
never an exception, never a crash — the same "framework only, no real backend" stance
`dispatcher/dispatcher.py`'s `on_dispatched`/`on_handler_error` hooks and `session/device_
session_manager.py`'s `on_device_online`/`on_device_offline` hooks already take for
not-yet-built observability/eventing infrastructure. It is *not* a fail-closed default the way
`NullDeviceProvisioningPort` (Phase 9.5) is — there is no accept/reject decision to make here,
only "durably deliver" vs. "log for now," so silently logging (rather than refusing to start)
is the correct default, not a security gap: no position data is exposed or acted on by logging
it, unlike auth/registration's fail-open would have been.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.events.device_position_reported import DevicePositionReported
from src.logging_setup import get_logger, log_with_fields

logger = get_logger("jt808.events.publisher")


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: DevicePositionReported) -> None:
        raise NotImplementedError


class LoggingEventPublisher(EventPublisher):
    """Default binding (`server.py`) until a real outbox+broker implementation exists."""

    async def publish(self, event: DevicePositionReported) -> None:
        log_with_fields(
            logger,
            20,
            "device_position_reported",
            organization_id=event.organization_id,
            vehicle_id=event.vehicle_id,
            device_id=event.device_id,
            terminal_id=event.terminal_id,
            trip_id=event.trip_id,
            latitude=event.latitude,
            longitude=event.longitude,
            speed_kph=event.speed_kph,
            heading_deg=event.heading_deg,
            alarm_flags=event.alarm_flags,
            event_time=event.event_time.isoformat(),
            is_backfill=event.is_backfill,
        )
