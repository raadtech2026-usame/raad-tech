"""Tracking event subscribers — closes the consumer half of roadmap track B2 (`docs/architecture/
frontend-flutter-master-roadmap.md` §4A). Consumes `DevicePositionReported` (published by the
device-plane service, `services/jt808/src/vendors/lsz_mdvr/` per ADR-0009) and persists it via
`TrackingApplicationService.record_vehicle_position`/`record_backfill_position` — the exact
"Business API-side tracking consumer" `services/jt808/src/handlers/location_handler.py`'s own
module docstring already names as a later phase's job, and `docs/vendor/
HARDWARE_INTEGRATION_PLAN.md` §12's "Required refactoring" step 3.

**Wire envelope this subscriber expects** (the contract the device-plane service's own publish
side must satisfy once it exists — see "Not yet wired" below): a `core.events.base.DomainEvent`
with `event_type="DevicePositionReported"`, `aggregate_type="Vehicle"`, `aggregate_id=vehicle_id`,
`org_id=organization_id`, and a `payload` carrying every field of `services/jt808/src/vendors/
lsz_mdvr/../events/device_position_reported.DevicePositionReported` by the same names
(`vehicle_id`, `device_id`, `terminal_id`, `trip_id`, `latitude`, `longitude`, `speed_kph`,
`heading_deg`, `alarm_flags`, `event_time` as an ISO-8601 string, `is_backfill`) — deliberately
the same field set `RecordVehiclePositionCommand`/`RecordBackfillPositionCommand` already expect,
so this processor does no renaming or unit conversion of its own, mirroring the device-plane
event's own module docstring ("a future Business API-side consumer can build one of those
commands from this event with no field renaming or unit conversion of its own").

**Not yet wired to a real broker consumer.** `core/di/bootstrap.py` registers this module's
processor onto the shared `EventProcessorRegistry` whenever a broker is configured (the same
`if settings.broker.url:` guard every other broker-dependent binding in that file already uses),
exactly like `notifications/events/subscribers.py`'s `register_notification_processors`. What is
genuinely **not yet built** is the *producer* side: the device-plane service's own `EventPublisher`
still defaults to `LoggingEventPublisher` (log-only) because publishing onto the shared `raad:
events` Redis Stream from a second, separate deployable needs its own Redis client dependency
approval for `services/jt808/pyproject.toml` (`.claude/rules/workflow.md` #1/#2 — proposed, not
yet approved, see that `pyproject.toml`'s own comment). This processor is real, tested, and ready
to receive events the moment that producer-side dependency is approved and wired — it is not
gated on anything in this codebase changing further.

**Idempotency:** `record_vehicle_position`/`record_backfill_position` each insert a new
`VehiclePosition` row with a freshly generated id — replaying the same `DevicePositionReported`
event (at-least-once delivery, Backend LLD §10.3) produces a harmless duplicate history row, not
a domain-rule violation or a crash. No de-duplication key exists for this event type in the
current schema; accepted as-is, matching `vehicle_positions`' own append-only, high-frequency,
retention-pruned design (`.claude/rules/database.md` #6) — a duplicate row ages out with the rest.
"""

from __future__ import annotations

from datetime import datetime

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.events.processor import EventProcessor, EventProcessorRegistry
from raad.modules.tracking.application.commands import (
    RecordBackfillPositionCommand,
    RecordVehiclePositionCommand,
)
from raad.modules.tracking.application.ports import TrackingUnitOfWork
from raad.modules.tracking.application.services import TrackingApplicationService


class DevicePositionReportedProcessor(EventProcessor):
    event_type = "DevicePositionReported"

    def __init__(self, container: Container) -> None:
        self._container = container

    async def process(self, event: DomainEvent) -> None:
        payload = event.payload
        organization_id = event.org_id or payload["organization_id"]
        event_time = _parse_iso(payload["event_time"])

        service = self._container.resolve(TrackingApplicationService)
        uow = self._container.resolve(TrackingUnitOfWork)

        if payload.get("is_backfill", False):
            await service.record_backfill_position(
                RecordBackfillPositionCommand(
                    organization_id=organization_id,
                    vehicle_id=payload["vehicle_id"],
                    device_id=payload["device_id"],
                    latitude=payload["latitude"],
                    longitude=payload["longitude"],
                    event_time=event_time,
                    trip_id=payload.get("trip_id"),
                    speed_kph=payload.get("speed_kph"),
                    heading_deg=payload.get("heading_deg"),
                    alarm_flags=payload.get("alarm_flags"),
                ),
                uow=uow,
            )
        else:
            await service.record_vehicle_position(
                RecordVehiclePositionCommand(
                    organization_id=organization_id,
                    vehicle_id=payload["vehicle_id"],
                    device_id=payload["device_id"],
                    latitude=payload["latitude"],
                    longitude=payload["longitude"],
                    event_time=event_time,
                    trip_id=payload.get("trip_id"),
                    speed_kph=payload.get("speed_kph"),
                    heading_deg=payload.get("heading_deg"),
                    alarm_flags=payload.get("alarm_flags"),
                ),
                uow=uow,
            )


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def register_tracking_processors(registry: EventProcessorRegistry, container: Container) -> None:
    """Called from `core/di/bootstrap.py` when wiring a broker consumer — mirrors `notifications
    .events.subscribers.register_notification_processors`'s identical shape exactly."""
    registry.register(DevicePositionReportedProcessor(container))
