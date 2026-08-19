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

import uuid
from datetime import datetime, timezone

from raad.core.di.container import Container
from raad.core.errors.exceptions import ConflictError
from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerPort
from raad.core.events.processor import EventProcessor, EventProcessorRegistry
from raad.core.logging.setup import get_logger
from raad.core.tenancy.principal import Principal, Role
from raad.modules.fleet_device.application.commands import (
    RecordAuthKeyHashCommand,
    RecordDeviceSeenCommand,
    RegisterCameraCommand,
)
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import DeviceApplicationService
from raad.modules.fleet_device.domain.value_objects import CameraPosition

SYSTEM_PRINCIPAL = Principal(user_id="system", role=Role.FOUNDER, org_id=None)

logger = get_logger("raad.fleet_device.events.subscribers")

# ADR-0030 — the exact same broker wire contract `video/infra/adapters.Jt1078RelayAdapter`
# already publishes on (`services/device-gateway/src/vendors/jt808/commands/
# redis_video_signaling_consumer.py`'s own `_RELEVANT_EVENT_TYPE`/`_BUILDERS`) — reused
# verbatim, not a new event family, since `query_av_attributes` is just one more entry in that
# consumer's existing command-dispatch table.
_SIGNAL_EVENT_TYPE = "Jt1078SignalCommandRequested"


class DeviceConnectivityProcessor(EventProcessor):
    """Handles both `DeviceOnline` and `DeviceOffline` with one processor class (parameterized
    by `event_type`) rather than two near-duplicate subclasses — both answer "when was this
    device last seen, and is it online right now" (ADR-0020 §3 added the second half; this
    processor already received both event types, so no second consumer was needed)."""

    def __init__(self, event_type: str, container: Container) -> None:
        self.event_type = event_type
        self._container = container

    async def process(self, event: DomainEvent) -> None:
        device_id = event.payload.get("device_id")
        if not device_id:
            return

        service = self._container.resolve(DeviceApplicationService)
        uow = self._container.resolve(FleetDeviceUnitOfWork)
        discover_terminal_id = await service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=device_id,
                seen_at=event.occurred_at,
                # ADR-0020 §3: this processor is registered once per event_type
                # ("DeviceOnline"/"DeviceOffline", see `register_fleet_device_processors`
                # below) — `self.event_type` already tells us which, no new signal needed.
                is_online=self.event_type == "DeviceOnline",
                actor=SYSTEM_PRINCIPAL,
            ),
            uow=uow,
        )
        if discover_terminal_id is not None:
            await self._publish_av_attributes_query(discover_terminal_id)

    async def _publish_av_attributes_query(self, terminal_id: str) -> None:
        """ADR-0030 — the "when" half of automatic channel discovery: the *first* `DeviceOnline`
        for a device that has never had discovery requested before (the guard `record_device_seen`
        already set, in the same transaction, before this runs). Reuses `Jt1078RelayAdapter`'s
        exact broker wire contract (`video/infra/adapters.py`'s own `_signal_device_start`) — a
        deliberate choice, not a coincidence: `query_av_attributes` is a JT/T 1078 A/V-family
        command like every other entry in device-gateway's `redis_video_signaling_consumer.
        _BUILDERS`, so publishing it through the *same* stream/event shape means no new consumer
        or wire contract was needed on the device-gateway side, only one new dispatch-table entry.

        **Fails silently (logged, not raised) when no broker is configured** — matches this
        backend's own established "optional dependency, degrade don't crash" posture for every
        broker-touching component (`core/di/bootstrap.py`'s own `try_resolve(BrokerPort)` calls);
        a dev/test environment with no broker still processes `DeviceOnline` for `last_seen_at`/
        `is_online` correctly, it just never gets to request channel discovery."""
        broker = self._container.try_resolve(BrokerPort)
        if broker is None:
            logger.info(
                "av_attributes_query_skipped_no_broker",
                extra={"terminal_id": terminal_id},
            )
            return
        correlation_id = str(uuid.uuid4())
        await broker.publish(
            DomainEvent(
                event_id=str(uuid.uuid4()),
                event_type=_SIGNAL_EVENT_TYPE,
                version=1,
                occurred_at=datetime.now(timezone.utc),
                org_id=None,
                correlation_id=correlation_id,
                payload={
                    "terminal_id": terminal_id,
                    "correlation_id": correlation_id,
                    "command": "query_av_attributes",
                    "fields": {},
                },
                aggregate_type="Device",
                aggregate_id=terminal_id,
            )
        )


class DeviceAuthCodeProcessor(EventProcessor):
    """ADR-0025 §3 — handles `DeviceAuthCodeIssued`, the device-gateway's own `0x0102`
    credential-hash mint event (`services/device-gateway/src/events/device_auth_code_issued.py`).
    Mirrors `DeviceConnectivityProcessor`'s identical shape: resolve `device_id` from the
    payload, call the corresponding application-service command, `SYSTEM_PRINCIPAL` actor."""

    event_type = "DeviceAuthCodeIssued"

    def __init__(self, container: Container) -> None:
        self._container = container

    async def process(self, event: DomainEvent) -> None:
        device_id = event.payload.get("device_id")
        auth_key_hash = event.payload.get("auth_key_hash")
        if not device_id or not auth_key_hash:
            return

        service = self._container.resolve(DeviceApplicationService)
        uow = self._container.resolve(FleetDeviceUnitOfWork)
        await service.record_auth_key_hash(
            RecordAuthKeyHashCommand(
                device_id=device_id,
                auth_key_hash=auth_key_hash,
                actor=SYSTEM_PRINCIPAL,
            ),
            uow=uow,
        )


class DeviceAvAttributesReportedProcessor(EventProcessor):
    """ADR-0030 — handles `DeviceAvAttributesReported`, device-gateway's `0x1003` reply to the
    `query_av_attributes` request `DeviceConnectivityProcessor._publish_av_attributes_query`
    sent. The "automatically create Camera records for every discovered channel" half of the
    workflow: RAAD derives channel *numbers* itself from the single `max_video_channels` count
    (Table 5.31's confirmed "1-based, starting from 1" convention — see `commands/
    av_attributes.py`'s own docstring on the device-gateway side) rather than expecting the
    terminal to enumerate them.

    **Position/label default (accepted design decision):** every auto-discovered camera gets
    `position=CameraPosition.OTHER`, `label=f"Channel {n}"` — RAAD does not guess semantic
    position (driver-facing/road-facing) from one vendor's own channel-numbering convention,
    since a different JT/T1078-compliant vendor's hardware may not follow it (ADR-0010's
    multi-vendor premise). An Org Admin can rename/reposition afterward through the ordinary
    camera-editing surface once one exists.

    **Idempotent by construction, not by a pre-check:** `register_camera` already enforces
    `ux_cameras__device_channel` (one `channel_no` per device) at the aggregate root
    (`Device.register_camera`, raises `ConflictError`) — a replayed/duplicate `0x1003` report
    (e.g. device-gateway restart, at-least-once broker delivery) simply finds every channel
    already registered and moves on, exactly the same "idempotent because the invariant already
    exists" posture this codebase already applies elsewhere rather than a separate dedup check."""

    event_type = "DeviceAvAttributesReported"

    def __init__(self, container: Container) -> None:
        self._container = container

    async def process(self, event: DomainEvent) -> None:
        device_id = event.payload.get("device_id")
        max_video_channels = event.payload.get("max_video_channels")
        if not device_id or not max_video_channels:
            return

        service = self._container.resolve(DeviceApplicationService)
        for channel_no in range(1, int(max_video_channels) + 1):
            uow = self._container.resolve(FleetDeviceUnitOfWork)
            try:
                await service.register_camera(
                    RegisterCameraCommand(
                        device_id=device_id,
                        channel_no=channel_no,
                        position=CameraPosition.OTHER,
                        label=f"Channel {channel_no}",
                        actor=SYSTEM_PRINCIPAL,
                    ),
                    uow=uow,
                )
            except ConflictError:
                logger.info(
                    "camera_channel_already_registered",
                    extra={"device_id": device_id, "channel_no": channel_no},
                )


def register_fleet_device_processors(
    registry: EventProcessorRegistry, container: Container
) -> None:
    """Called from `core/di/bootstrap.py` when wiring a broker consumer — mirrors `tracking.
    events.subscribers.register_tracking_processors`'s identical shape exactly."""
    registry.register(DeviceConnectivityProcessor("DeviceOnline", container))
    registry.register(DeviceConnectivityProcessor("DeviceOffline", container))
    registry.register(DeviceAuthCodeProcessor(container))
    registry.register(DeviceAvAttributesReportedProcessor(container))
