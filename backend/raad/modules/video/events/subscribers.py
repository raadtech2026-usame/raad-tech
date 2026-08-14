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

**`ParentVideoLiveAccessRevokedProcessor`/`ParentVideoPlaybackAccessRevokedProcessor`
(stale-permission fix, focused D5 review, 2026-08-13).** Two new processors for two
`transport_ops`-owned events (`ParentVideoLiveAccessRevoked`/`ParentVideoPlaybackAccessRevoked`,
`transport_ops/domain/events.py`) — the same cross-module event-subscription shape
`notifications/events/subscribers.py` already establishes for consuming `transport_ops`'s
`TripStarted`/`TripEnded` (this file already imported nothing from `transport_ops`, but the
pattern — resolve the owning module's application service fresh from the `Container`, never a
cross-module DB read — is identical). Revoking `has_video_live_access`/`has_video_playback_access`
previously only flipped the `Parent` boolean; a parent already mid-stream kept receiving media
until the session's own natural timeout, since nothing tore down an already-`REQUESTED`/`ACTIVE`
`VideoSession`. These processors close that gap by reusing the *existing* `VideoSession` ->
`VideoProviderPort` -> JT1078 relay stop lifecycle (`VideoApplicationService.stop_video_session`,
unchanged in shape, now idempotent on its provider-facing side too — see that method's own
docstring) — never a parallel/duplicate stop path. `parent_id` comes from the revoke event's own
`aggregate_id` (`transport_ops_events.parent_video_live_access_revoked`/`..._playback_...` put it
there, not in `payload` — mirrors every other module's own event factory, `payload={"actor_id":
...}` only); this backend has no row for a genuinely deleted `Parent`, or a session-less parent,
which is expected and not an error (same "no-op, not a failure" contract every relay-event
processor above already establishes)."""

from __future__ import annotations

from raad.core.di.container import Container
from raad.core.errors.exceptions import NotFoundError
from raad.core.events.base import DomainEvent
from raad.core.events.processor import EventProcessor, EventProcessorRegistry
from raad.core.tenancy.principal import Principal, Role
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import GetParentByIdQuery
from raad.modules.transport_ops.application.services import ParentApplicationService
from raad.modules.video.application.commands import (
    MarkVideoSessionActiveCommand,
    MarkVideoSessionEndedCommand,
    MarkVideoSessionFailedCommand,
    StopVideoSessionCommand,
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


class _ParentVideoAccessRevokedHandler:
    """Shared logic behind both revoke processors below — the only difference between "live"
    and "playback" is which purpose to filter/stop, so the orchestration itself is written once.
    Never called directly by anything except its own two thin `EventProcessor` wrappers."""

    def __init__(self, container: Container, *, purpose: str) -> None:
        self._container = container
        self._purpose = purpose

    async def handle(self, event: DomainEvent) -> None:
        parent_id = event.aggregate_id
        if not parent_id:
            return

        parent_service = self._container.resolve(ParentApplicationService)
        transport_ops_uow = self._container.resolve(TransportOpsUnitOfWork)
        try:
            parent = await parent_service.get_parent_by_id(
                GetParentByIdQuery(parent_id=parent_id), uow=transport_ops_uow
            )
        except NotFoundError:
            # The parent row is gone by the time this event is processed - a real, expected
            # race (deletion/reassignment), not an error - mirrors every processor above's own
            # "a lifecycle event for a row this backend no longer has is expected" contract.
            return

        video_service = self._container.resolve(VideoApplicationService)
        video_uow = self._container.resolve(VideoUnitOfWork)
        sessions = await video_service.list_active_sessions_for_requester(
            requested_by_user_id=parent.user_id, purpose=self._purpose, uow=video_uow
        )
        for session in sessions:
            # `stop_video_session` re-resolves the session fresh from `uow` and is itself
            # idempotent on the provider-facing side (`application/services.py`'s own docstring)
            # - safe to call once per session found here, and safe under at-least-once event
            # redelivery: a redelivered event's own fresh `list_active_sessions_for_requester`
            # call simply finds nothing left to stop.
            await video_service.stop_video_session(
                StopVideoSessionCommand(video_session_id=session.id, actor=SYSTEM_PRINCIPAL),
                uow=video_uow,
            )


class ParentVideoLiveAccessRevokedProcessor(EventProcessor):
    """Stale-permission fix: tears down every `REQUESTED`/`ACTIVE` *live* session the
    now-revoked parent still has open, via the existing stop lifecycle."""

    event_type = "ParentVideoLiveAccessRevoked"

    def __init__(self, container: Container) -> None:
        self._handler = _ParentVideoAccessRevokedHandler(container, purpose="live")

    async def process(self, event: DomainEvent) -> None:
        await self._handler.handle(event)


class ParentVideoPlaybackAccessRevokedProcessor(EventProcessor):
    """Same as `ParentVideoLiveAccessRevokedProcessor`, for *playback* sessions."""

    event_type = "ParentVideoPlaybackAccessRevoked"

    def __init__(self, container: Container) -> None:
        self._handler = _ParentVideoAccessRevokedHandler(container, purpose="playback")

    async def process(self, event: DomainEvent) -> None:
        await self._handler.handle(event)


def register_video_processors(registry: EventProcessorRegistry, container: Container) -> None:
    """Called from `core/di/bootstrap.py` when wiring a broker consumer — mirrors
    `fleet_device.events.subscribers.register_fleet_device_processors`'s identical shape."""
    registry.register(VideoSessionActivatedProcessor(container))
    registry.register(VideoSessionEndedProcessor(container))
    registry.register(VideoSessionFailedProcessor(container))
    registry.register(ParentVideoLiveAccessRevokedProcessor(container))
    registry.register(ParentVideoPlaybackAccessRevokedProcessor(container))
