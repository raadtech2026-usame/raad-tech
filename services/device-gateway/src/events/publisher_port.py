"""`EventPublisher` — the port every vendor adapter's handlers use to hand off a device-plane
domain event, instead of ever calling into `tracking` (or any other business module) directly
(Phase 9.6; see `device_position_reported.py`'s module docstring for the full architecture
rationale). Widened (device-gateway Redis integration) from `DevicePositionReported` alone to
`DeviceEvent`, the union of all four events `.claude/rules/jt808.md` #1/`architecture.md` #3 name
as this deployable's complete published-event vocabulary — `DeviceOnline`/`DeviceOffline` are now
real, publishable dataclasses (`device_online.py`/`device_offline.py`), and `DeviceAlarmRaised`
(`device_alarm_raised.py`) is defined for completeness even though no handler constructs one yet.

**Vendor-agnostic by construction:** every vendor adapter (`vendors/jt808/`, `vendors/lsz/`, any
future `vendors/<name>/`) constructs the *same* event dataclasses and publishes them through the
*same* `EventPublisher` instance — this port has no vendor-specific branch anywhere, and the
Business Plane consuming published events downstream has no way to tell which vendor produced
any given one (this refactor's own explicit "Business Plane must never know which protocol"
requirement, satisfied at this exact seam).

`LoggingEventPublisher` is the default until a real broker is configured — publishing degrades to
a structured log line, never an exception, never a crash — the same "framework only, no real
backend" stance `dispatcher/dispatcher.py`'s `on_dispatched`/`on_handler_error` hooks already take
for not-yet-built observability infrastructure. It is *not* a fail-closed default the way
`NullDeviceProvisioningPort` is — there is no accept/reject decision here, only "durably deliver"
vs. "log for now," so silently logging is the correct default, not a security gap.

**`RedisEventPublisher`** (device-gateway Redis integration, `redis_event_publisher.py`) is the
real, broker-backed implementation — see that module's own docstring.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Union

from src.events.device_alarm_raised import DeviceAlarmRaised
from src.events.device_auth_code_issued import DeviceAuthCodeIssued
from src.events.device_offline import DeviceOffline
from src.events.device_online import DeviceOnline
from src.events.device_position_reported import DevicePositionReported
from src.logging_setup import get_logger, log_with_fields

logger = get_logger("device_gateway.events.publisher")

DeviceEvent = Union[
    DevicePositionReported,
    DeviceOnline,
    DeviceOffline,
    DeviceAlarmRaised,
    DeviceAuthCodeIssued,
]


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: DeviceEvent) -> None:
        raise NotImplementedError


class LoggingEventPublisher(EventPublisher):
    """Default binding (every vendor adapter's `server.py`) until a real broker is configured."""

    async def publish(self, event: DeviceEvent) -> None:
        if isinstance(event, DevicePositionReported):
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
        elif isinstance(event, DeviceOnline):
            log_with_fields(
                logger,
                20,
                "device_online",
                organization_id=event.organization_id,
                vehicle_id=event.vehicle_id,
                device_id=event.device_id,
                terminal_id=event.terminal_id,
                event_time=event.event_time.isoformat(),
            )
        elif isinstance(event, DeviceOffline):
            log_with_fields(
                logger,
                20,
                "device_offline",
                organization_id=event.organization_id,
                vehicle_id=event.vehicle_id,
                device_id=event.device_id,
                terminal_id=event.terminal_id,
                reason=event.reason,
                event_time=event.event_time.isoformat(),
            )
        elif isinstance(event, DeviceAlarmRaised):
            log_with_fields(
                logger,
                30,
                "device_alarm_raised",
                organization_id=event.organization_id,
                vehicle_id=event.vehicle_id,
                device_id=event.device_id,
                terminal_id=event.terminal_id,
                alarm_type=event.alarm_type,
                alarm_flags=event.alarm_flags,
                event_time=event.event_time.isoformat(),
            )
        elif isinstance(event, DeviceAuthCodeIssued):
            log_with_fields(
                logger,
                20,
                "device_auth_code_issued",
                organization_id=event.organization_id,
                vehicle_id=event.vehicle_id,
                device_id=event.device_id,
                terminal_id=event.terminal_id,
                event_time=event.event_time.isoformat(),
            )
