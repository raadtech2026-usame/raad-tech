"""Video event subscribers (ADR-0026 §7) — closes the gap the JT1078 backend-integration
phase's own report disclosed: `services/jt1078`'s `RedisSessionEventPublisher` has published
`VideoSessionActivated`/`VideoSessionEnded`/`VideoSessionFailed` since that phase, but nothing on
this backend ever consumed them — `VideoSession.status` was driven entirely by an eager,
optimistic `activate()` call right after the provider RPC returned (`application/services.py`,
removed by this same ADR), never by the relay's own observed reality.

**Wire envelope this subscriber expects** (`services/jt1078/src/events/
redis_session_event_publisher.py`'s own `_fields_for`): `event_type="VideoSessionActivated"` /
`"VideoSessionEnded"` / `"VideoSessionFailed"`, `aggregate_type="VideoSession"`, `payload`
carrying `session_id` (the relay's own session id — which **is** the Business API's own
`VideoSession.id`, the existing session-id passthrough design, JT1078 backend-integration phase),
plus `terminal_id`/`organization_id`/`vehicle_id`/`device_id`/`correlation_id` (not needed here —
the session row already carries its own `device_id`/`organization_id`) and, for `Ended`/`Failed`,
`reason`.

**A lifecycle event for a `session_id` this backend has no row for is expected, not an error** —
mirrors `fleet_device/events/subscribers.py`'s identical "a connectivity event for a device_id
this backend never registered is expected" precedent (a race between this backend's own request
flow and the relay's is always possible; `VideoApplicationService.mark_session_*`'s own
docstrings cover the no-op case, not duplicated here).

**`SYSTEM_PRINCIPAL`** — mirrors `fleet_device/events/subscribers.py`'s own already-established,
already-flagged precedent verbatim (duplicated per module, not shared, the same reasoning
`_AggregateRoot` is duplicated per module for).
"""

from __future__ import annotations

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.events.processor import EventProcessor, EventProcessorRegistry
from raad.core.tenancy.principal import Principal, Role
from raad.modules.video.application.commands import (
    MarkVideoSessionActiveCommand,
    MarkVideoSessionEndedCommand,
    MarkVideoSessionFailedCommand,
)
from raad.modules.video.application.ports import VideoUnitOfWork
from raad.modules.video.application.services import VideoApplicationService

SYSTEM_PRINCIPAL = Principal(user_id="system", role=Role.FOUNDER, org_id=None)


class VideoSessionActivatedProcessor(EventProcessor):
    event_type = "VideoSessionActivated"

    def __init__(self, container: Container) -> None:
        self._container = container

    async def process(self, event: DomainEvent) -> None:
        session_id = event.payload.get("session_id")
        if not session_id:
            return
        service = self._container.resolve(VideoApplicationService)
        uow = self._container.resolve(VideoUnitOfWork)
        await service.mark_session_active(
            MarkVideoSessionActiveCommand(video_session_id=session_id, actor=SYSTEM_PRINCIPAL),
            uow=uow,
        )


class VideoSessionEndedProcessor(EventProcessor):
    event_type = "VideoSessionEnded"

    def __init__(self, container: Container) -> None:
        self._container = container

    async def process(self, event: DomainEvent) -> None:
        session_id = event.payload.get("session_id")
        if not session_id:
            return
        service = self._container.resolve(VideoApplicationService)
        uow = self._container.resolve(VideoUnitOfWork)
        await service.mark_session_ended(
            MarkVideoSessionEndedCommand(
                video_session_id=session_id,
                reason=event.payload.get("reason"),
                actor=SYSTEM_PRINCIPAL,
            ),
            uow=uow,
        )


class VideoSessionFailedProcessor(EventProcessor):
    event_type = "VideoSessionFailed"

    def __init__(self, container: Container) -> None:
        self._container = container

    async def process(self, event: DomainEvent) -> None:
        session_id = event.payload.get("session_id")
        if not session_id:
            return
        service = self._container.resolve(VideoApplicationService)
        uow = self._container.resolve(VideoUnitOfWork)
        await service.mark_session_failed(
            MarkVideoSessionFailedCommand(
                video_session_id=session_id,
                reason=event.payload.get("reason"),
                actor=SYSTEM_PRINCIPAL,
            ),
            uow=uow,
        )


def register_video_processors(registry: EventProcessorRegistry, container: Container) -> None:
    """Called from `core/di/bootstrap.py` when wiring a broker consumer — mirrors
    `fleet_device.events.subscribers.register_fleet_device_processors`'s identical shape."""
    registry.register(VideoSessionActivatedProcessor(container))
    registry.register(VideoSessionEndedProcessor(container))
    registry.register(VideoSessionFailedProcessor(container))
