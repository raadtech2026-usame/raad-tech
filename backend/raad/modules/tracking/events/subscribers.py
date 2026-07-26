"""Tracking event subscribers — closes the consumer half of roadmap track B2 (`docs/architecture/
frontend-flutter-master-roadmap.md` §4A). Consumes `DevicePositionReported` (published by the
device-plane service, `services/device-gateway/src/vendors/lsz/` per ADR-0009/ADR-0010 — this
docstring previously referenced the pre-rename `services/jt808/src/vendors/lsz_mdvr/` path,
corrected below) and persists it via `TrackingApplicationService.record_vehicle_position`/
`record_backfill_position` — the exact "Business API-side tracking consumer"
`services/device-gateway/src/vendors/lsz/handlers/position_handler.py`'s own module docstring
already names as a later phase's job, and `docs/vendor/HARDWARE_INTEGRATION_PLAN.md` §12's
"Required refactoring" step 3.

**Wire envelope this subscriber expects:** a `core.events.base.DomainEvent` with
`event_type="DevicePositionReported"`, `aggregate_type="Vehicle"`, `aggregate_id=vehicle_id`,
`org_id=organization_id`, and a `payload` carrying every field of `services/device-gateway/src/
events/device_position_reported.DevicePositionReported` by the same names (`vehicle_id`,
`device_id`, `terminal_id`, `trip_id`, `latitude`, `longitude`, `speed_kph`, `heading_deg`,
`alarm_flags`, `event_time` as an ISO-8601 string, `is_backfill`) — deliberately the same field set
`RecordVehiclePositionCommand`/`RecordBackfillPositionCommand` already expect, so this processor
does no renaming or unit conversion of its own, mirroring the device-plane event's own module
docstring ("a future Business API-side consumer can build one of those commands from this event
with no field renaming or unit conversion of its own").

**Now live-verified, end-to-end, against a real Redis and a real Postgres (ADR-0012 follow-up
verification pass).** This paragraph previously said the producer-side Redis dependency was
"proposed, not yet approved" and that the whole path was "not yet wired to a real broker
consumer" — both stale as of this correction: `services/device-gateway/pyproject.toml` marks
`redis>=5.0` **APPROVED** (user-confirmed), `RedisEventPublisher` is wired into
`vendors/lsz/server.py`, and `core/di/bootstrap.py` binds this module's `DevicePositionReportedProcessor`
onto the same `notification-worker` consumer group `NotificationWorker` already ticks (a single
shared `EventProcessorRegistry`, not a dedicated tracking worker). A real LSZ registration+position
frame, sent over a real TCP socket through a real `MdvrServer` → `RedisEventPublisher` → `raad:
events` Stream → this exact processor → a real `TrackingApplicationService` → a real, committed
`vehicle_positions` row was proven in this pass (`services/device-gateway/scripts/
verify_redis_e2e.py`, plus a direct processor invocation against a live Postgres instance).
**A real bug was found and fixed during this same pass**, not just a missing-infrastructure
gap: `position_handler.py` was passing the vendor's raw, out-of-spec `heading_deg`/`alarm_flags`
values straight through to `RecordVehiclePositionCommand` without range-checking them first, so
`tracking.domain.value_objects.HeadingDegrees`/`AlarmFlags` correctly rejected them with a
`DomainError` — silently failing *every* real position event from this vendor forever (both of
the vendor's own documented worked examples fall outside the valid ranges, so this was not a rare
edge case). Fixed at the source (`position_handler.py`'s own range-clamp, see its module
docstring) — this file needed no change, since the bug was in what the producer sent, not in how
this processor consumes it.

**Still not proven "live at rest"**, distinct from the above: the standing worker process
(`python -m raad.interfaces.workers.bootstrap`, the same consumer group) has a large pre-existing
`outbox` backlog from prior, unrelated integration-test runs (700+ historical domain events,
newly draining now that a broker is reachable for the first time) — a running worker will reach
and correctly process new live position events once it works through that backlog, but this was
proven directly (a single processor invocation against the newest published event, not by
observing the standing worker specifically clear that backlog and reach it live). Also still
genuinely unbuilt: `vehicle:{id}:last`'s direct Redis cache write (B2's own scope,
`GET /tracking/vehicles/{id}/latest`'s instant-read source) — no code in `services/device-gateway`
writes this key yet; grepped for and confirmed absent in this same pass. This processor is not
gated on anything in this codebase changing further.

**Idempotency:** `record_vehicle_position`/`record_backfill_position` each insert a new
`VehiclePosition` row with a freshly generated id — replaying the same `DevicePositionReported`
event (at-least-once delivery, Backend LLD §10.3) produces a harmless duplicate history row, not
a domain-rule violation or a crash. No de-duplication key exists for this event type in the
current schema; accepted as-is, matching `vehicle_positions`' own append-only, high-frequency,
retention-pruned design (`.claude/rules/database.md` #6) — a duplicate row ages out with the rest.

**Active-trip resolution (`docs/architecture/post-f7-production-readiness-roadmap.md` Phase A
item A4).** Every device-plane vendor adapter today publishes `DevicePositionReported` with
`trip_id=None` — confirmed for LSZ (`services/device-gateway/src/vendors/lsz/handlers/
position_handler.py`'s own docstring: "no active-trip Redis read-model exists in this
deployable... the Business API's consumer resolves/repairs it", `device_position_reported.py`).
**This processor is that consumer.** For a live (non-backfill) position, `trip_id` is resolved
fresh, on every event, via `transport_ops`'s own `TripApplicationService.
get_active_trip_for_vehicle` — a cross-module *application-service* call (`.claude/rules/
backend.md` #3: never a direct repository/DB read into another module's tables) — and that
resolved value is used **unconditionally**, not merely as a fallback when the payload's own
`trip_id` is absent: the device plane has no visibility into `transport_ops`'s trip state at all
(by architecture, `.claude/rules/architecture.md` #2/#3), so a backend-resolved value is always
more authoritative than anything a vendor adapter could have attached. This closes a real,
previously-silent gap the audit itself did not spell out to its actual consequence: without it,
`GET /tracking/trips/{id}/positions` returns an empty page for every trip a real device ever
drives, forever, since no real position was ever persisted with a non-null `trip_id`.

**Backfilled positions are deliberately exempted from this resolution** — `payload.get("trip_id")`
is used as-is (today, always `None`, since no vendor adapter publishes backfill events yet).
Resolving "the vehicle's *currently* active trip" for a late-arriving, past-dated position would
misattribute it: the currently active trip (if any) is very likely not the trip that was active
at the buffered position's own `event_time`. No historical trip-lookup capability exists to do
this correctly for backfill, so it is left unresolved rather than resolved wrong — the same
"backfilled points are excluded" carve-out Phase 2 §22.2 already establishes for geofence
evaluation, applied here to trip attribution instead.
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
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import GetActiveTripForVehicleQuery
from raad.modules.transport_ops.application.services import TripApplicationService


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
            trip_id = await self._resolve_active_trip_id(payload["vehicle_id"])
            await service.record_vehicle_position(
                RecordVehiclePositionCommand(
                    organization_id=organization_id,
                    vehicle_id=payload["vehicle_id"],
                    device_id=payload["device_id"],
                    latitude=payload["latitude"],
                    longitude=payload["longitude"],
                    event_time=event_time,
                    trip_id=trip_id,
                    speed_kph=payload.get("speed_kph"),
                    heading_deg=payload.get("heading_deg"),
                    alarm_flags=payload.get("alarm_flags"),
                ),
                uow=uow,
            )

    async def _resolve_active_trip_id(self, vehicle_id: str) -> str | None:
        trip_service = self._container.resolve(TripApplicationService)
        transport_ops_uow = self._container.resolve(TransportOpsUnitOfWork)
        trip = await trip_service.get_active_trip_for_vehicle(
            GetActiveTripForVehicleQuery(vehicle_id=vehicle_id), uow=transport_ops_uow
        )
        return trip.id if trip is not None else None


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def register_tracking_processors(registry: EventProcessorRegistry, container: Container) -> None:
    """Called from `core/di/bootstrap.py` when wiring a broker consumer — mirrors `notifications
    .events.subscribers.register_notification_processors`'s identical shape exactly."""
    registry.register(DevicePositionReportedProcessor(container))
