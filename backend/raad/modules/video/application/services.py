"""Video application service (Backend LLD §4.1/§4.3). One `VideoApplicationService` class
covering the module's single aggregate, mirroring `billing.application.services.
BillingApplicationService`'s shape.

**`video_provider: VideoProviderPort | None = None` — the identical, already-established
"fail loudly at the one call site that needs it, not the whole service" pattern
`BillingApplicationService.__init__`'s own docstring documents for `PaymentProviderPort`.**
`request_live_video`/`request_playback_video` persist the `VideoSession` as `REQUESTED` (a
real, complete, testable action needing no provider) before ever touching
`self._video_provider`; only the subsequent activation step raises `NotImplementedError` when
unbound. This phase's own explicit instruction ("Implement only the abstraction layer if
needed... Native JT1078 implementation is intentionally postponed") is exactly why no concrete
adapter is bound in `core/di/bootstrap.py` this phase.

**No `try/except` around the provider call, deliberately.** Unlike a hypothetical retry/
compensating-transaction wrapper, nothing in any approved document describes what should happen
if a bound provider's `start_live`/`start_playback` raises — mirroring `BillingApplicationService.
initiate_payment`'s identical choice to let `self._payment_provider.charge(...)` propagate
uncaught rather than inventing failure-handling behavior no document specifies.
`VideoSession.fail()` exists for completeness of the documented status enum (mirrors `Subscription.
suspend`/`cancel`'s "documented value, no documented trigger" posture) but nothing calls it this
phase.
"""

from __future__ import annotations

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.time.clock import Clock
from raad.modules.video.application.commands import (
    RequestLiveVideoCommand,
    RequestPlaybackVideoCommand,
    StopVideoSessionCommand,
)
from raad.modules.video.application.ports import VideoProviderPort, VideoUnitOfWork
from raad.modules.video.application.queries import (
    GetVideoSessionByIdQuery,
    VideoSessionDTO,
    video_session_to_dto,
)
from raad.modules.video.domain.entities import VideoSession
from raad.modules.video.domain.value_objects import (
    CameraId,
    DeviceId,
    OrganizationId,
    UserId,
    VideoSessionId,
)


class VideoApplicationService:
    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        video_provider: VideoProviderPort | None = None,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._video_provider = video_provider

    async def request_live_video(
        self, command: RequestLiveVideoCommand, *, uow: VideoUnitOfWork
    ) -> VideoSessionDTO:
        """`POST /video/live`. D5 authorization has already run (`interfaces/http/
        policy_guards.enforce_d5`) before this is ever called — see `entities.py`'s
        `VideoSession` docstring."""
        async with uow:
            session = VideoSession.request_live(
                id=VideoSessionId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                device_id=DeviceId(command.device_id),
                camera_id=CameraId(command.camera_id),
                requested_by=UserId(command.actor.user_id),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.video_sessions.add(session)
            uow.record_events(session.pull_domain_events())
            await uow.commit()

        if self._video_provider is None:
            raise NotImplementedError(
                "No VideoProviderPort is bound - this phase deliberately does not integrate "
                "with a live hardware/vendor video API (native JT1078 is intentionally "
                "postponed). The VideoSession row above was persisted as REQUESTED; activating "
                "it requires a future phase's concrete adapter (see infra/adapters.py's module "
                "docstring)."
            )

        stream_url = await self._video_provider.start_live(
            device_id=command.device_id,
            camera_id=command.camera_id,
            reference=str(session.id),
        )
        async with uow:
            session = await self._get_session_or_raise(uow, str(session.id))
            session.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(session.pull_domain_events())
            await uow.commit()
            return video_session_to_dto(session, stream_url=stream_url)

    async def request_playback_video(
        self, command: RequestPlaybackVideoCommand, *, uow: VideoUnitOfWork
    ) -> VideoSessionDTO:
        """`POST /video/playback`."""
        async with uow:
            session = VideoSession.request_playback(
                id=VideoSessionId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                device_id=DeviceId(command.device_id),
                camera_id=CameraId(command.camera_id),
                requested_by=UserId(command.actor.user_id),
                window_start=command.window_start,
                window_end=command.window_end,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.video_sessions.add(session)
            uow.record_events(session.pull_domain_events())
            await uow.commit()

        if self._video_provider is None:
            raise NotImplementedError(
                "No VideoProviderPort is bound - see request_live_video's identical message."
            )

        stream_url = await self._video_provider.start_playback(
            device_id=command.device_id,
            camera_id=command.camera_id,
            window_start=command.window_start,
            window_end=command.window_end,
            reference=str(session.id),
        )
        async with uow:
            session = await self._get_session_or_raise(uow, str(session.id))
            session.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(session.pull_domain_events())
            await uow.commit()
            return video_session_to_dto(session, stream_url=stream_url)

    async def stop_video_session(
        self, command: StopVideoSessionCommand, *, uow: VideoUnitOfWork
    ) -> VideoSessionDTO:
        """`POST /video/sessions/{id}/stop`. Unlike the two request methods, a missing
        `VideoProviderPort` does not block ending the session locally — `end()` still runs, so a
        control record can always be closed out even if the vendor-side teardown itself could
        not be attempted."""
        async with uow:
            session = await self._get_session_or_raise(uow, command.video_session_id)

        if self._video_provider is not None:
            await self._video_provider.stop(reference=str(session.id))

        async with uow:
            session = await self._get_session_or_raise(uow, command.video_session_id)
            session.end(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(session.pull_domain_events())
            await uow.commit()
            return video_session_to_dto(session)

    async def get_video_session_by_id(
        self, query: GetVideoSessionByIdQuery, *, uow: VideoUnitOfWork
    ) -> VideoSessionDTO:
        async with uow:
            session = await self._get_session_or_raise(uow, query.video_session_id)
            return video_session_to_dto(session)

    @staticmethod
    async def _get_session_or_raise(
        uow: VideoUnitOfWork, video_session_id: str
    ) -> VideoSession:
        session = await uow.video_sessions.get(VideoSessionId(video_session_id))
        if session is None:
            raise NotFoundError(f"VideoSession {video_session_id} not found.")
        return session
