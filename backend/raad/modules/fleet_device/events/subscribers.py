"""Fleet & Device event subscribers — closes `docs/architecture/
post-f7-production-readiness-roadmap.md`'s Phase A item A3: `DeviceOnline`/`DeviceOffline` are
already real, published events (`services/device-gateway/src/vendors/lsz/server.py`'s
`_on_device_online`/`_on_device_offline`, via `RedisEventPublisher`), but nothing on this backend
ever consumed either — confirmed by this file previously being empty. `devices.last_seen_at`
(Database Design §5.2, already a real, migrated column) stayed `NULL` forever as a result, exactly
as `fleet_device/api/routers.py`'s own module docstring already flagged.

**Wire envelope this subscriber expects** (`services/device-gateway/src/events/
redis_event_publisher.py`'s own `_fields_for`): `event_type="DeviceOnline"` or `"DeviceOffline"`,
`aggregate_type="Device"`, `aggregate_id=terminal_id`, `payload` carrying `organization_id`,
`vehicle_id`, `device_id` (all optional per `DeviceSession`'s own pass-through typing — an
online/offline connectivity fact is still meaningful even if enrichment is incomplete, per
`device_online.py`'s own docstring) and, for `DeviceOffline` only, `reason` (not needed here — no
durable record of *why* a device went offline exists yet; only *that* it did, via the timestamp).
`seen_at` is read from the envelope's own `occurred_at` (the event's real timestamp), not the
payload — neither event's payload carries a timestamp field of its own.

**A connectivity event for a `device_id` this backend never registered is expected, not an
error** — `DeviceApplicationService.record_device_seen`'s own docstring covers the no-op case;
this processor does not duplicate that check. A `device_id` that is `None`/absent entirely
(possible per the optional typing above) is dropped silently here instead — there is nothing to
attach the fact to.

**`SYSTEM_PRINCIPAL`** — mirrors `notifications/events/subscribers.py`'s own already-established,
already-flagged precedent verbatim (see that module's docstring for the full "no approved
system/worker actor concept exists yet" reasoning): every application command in this codebase
requires `actor: Principal`, including this one, and no eighth `Role` exists for a background
process. `Principal(user_id="system", role=Role.FOUNDER, org_id=None)` is reused here rather than
re-derived, so `audit_entries.actor_user_id` reads the same `"system"` sentinel across every
broker-driven consumer in this codebase, not a per-module variant.
"""

from __future__ import annotations

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.events.processor import EventProcessor, EventProcessorRegistry
from raad.core.tenancy.principal import Principal, Role
from raad.modules.fleet_device.application.commands import RecordDeviceSeenCommand
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import DeviceApplicationService

SYSTEM_PRINCIPAL = Principal(user_id="system", role=Role.FOUNDER, org_id=None)


class DeviceConnectivityProcessor(EventProcessor):
    """Handles both `DeviceOnline` and `DeviceOffline` identically — both exist, for this
    backend's purposes, only to answer "when was this device last seen", so one processor class
    (parameterized by `event_type`) covers both rather than two near-duplicate subclasses."""

    def __init__(self, event_type: str, container: Container) -> None:
        self.event_type = event_type
        self._container = container

    async def process(self, event: DomainEvent) -> None:
        device_id = event.payload.get("device_id")
        if not device_id:
            return

        service = self._container.resolve(DeviceApplicationService)
        uow = self._container.resolve(FleetDeviceUnitOfWork)
        await service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=device_id,
                seen_at=event.occurred_at,
                actor=SYSTEM_PRINCIPAL,
            ),
            uow=uow,
        )


def register_fleet_device_processors(
    registry: EventProcessorRegistry, container: Container
) -> None:
    """Called from `core/di/bootstrap.py` when wiring a broker consumer — mirrors `tracking.
    events.subscribers.register_tracking_processors`'s identical shape exactly."""
    registry.register(DeviceConnectivityProcessor("DeviceOnline", container))
    registry.register(DeviceConnectivityProcessor("DeviceOffline", container))
