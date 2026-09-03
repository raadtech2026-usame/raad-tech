"""Video application service (Backend LLD §4.1/§4.3). One `VideoApplicationService` class
covering the module's single aggregate, mirroring `billing.application.services.
BillingApplicationService`'s shape.

**`video_provider: VideoProviderPort | None = None` — the identical, already-established
"fail loudly at the one call site that needs it, not the whole service" pattern
`BillingApplicationService.__init__`'s own docstring documents for `PaymentProviderPort`.**
`request_live_video`/`request_playback_video` persist the `VideoSession` as `REQUESTED` (a
real, complete, testable action needing no provider) before ever touching
`self._video_provider`; the subsequent provider call raises `NotImplementedError` when unbound
(no adapter conditionally bound in `core/di/bootstrap.py`) or, when bound, calls `Jt1078RelayAdapter`
(JT1078 backend-integration phase).

**No `try/except` around the provider call, deliberately.** Unlike a hypothetical retry/
compensating-transaction wrapper, nothing in any approved document describes what should happen
if a bound provider's `start_live`/`start_playback` raises — mirroring `BillingApplicationService.
initiate_payment`'s identical choice to let `self._payment_provider.charge(...)` propagate
uncaught rather than inventing failure-handling behavior no document specifies.

**`session.activate()` is no longer called eagerly here (ADR-0026 §7).** Both request methods
used to call it synchronously right after the provider RPC returned — before the relay had any
real signal that media was actually flowing. `VideoSession` now stays `REQUESTED` until
`events/subscribers.VideoSessionLifecycleProcessor` consumes the relay's own
`VideoSessionActivated`/`VideoSessionEnded`/`VideoSessionFailed` events (already published by
`services/jt1078`) and calls `activate`/`end`/`fail` through a fresh `VideoUnitOfWork` — the
first real caller of `VideoSession.fail()` in this codebase. `stream_url` is still returned
immediately in the API response; it never depended on persisted `status`
(`queries.video_session_to_dto`'s own signature).
"""

from __future__ import annotations

from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.logging.setup import get_logger
from raad.core.time.clock import Clock
from raad.modules.video.application.commands import (
    MarkVideoSessionActiveCommand,
    MarkVideoSessionEndedCommand,
    MarkVideoSessionFailedCommand,
    RequestIntercomCommand,
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
    VideoPurpose,
    VideoSessionId,
    VideoSessionStatus,
)

_OPEN_STATUSES = (VideoSessionStatus.REQUESTED, VideoSessionStatus.ACTIVE)
_TERMINAL_STATUSES = (VideoSessionStatus.ENDED, VideoSessionStatus.FAILED)

logger = get_logger("raad.video.application")


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
            terminal_id=command.terminal_id,
            channel_no=command.channel_no,
            reference=str(session.id),
            audio_codec=command.audio_codec,
        )
        # ADR-0026 §7: no eager `session.activate()` here - the relay hasn't confirmed media is
        # actually flowing yet (only that the RPC + device signal succeeded). `status` stays
        # `REQUESTED` until `events/subscribers.py`'s `VideoSessionLifecycleProcessor` consumes
        # the relay's own `VideoSessionActivated` event. `stream_url` is still returned
        # immediately - it never depended on persisted `status` (`queries.video_session_to_dto`).
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
            terminal_id=command.terminal_id,
            channel_no=command.channel_no,
            window_start=command.window_start,
            window_end=command.window_end,
            reference=str(session.id),
            audio_codec=command.audio_codec,
        )
        # ADR-0026 §7: same reasoning as request_live_video above - no eager activate().
        return video_session_to_dto(session, stream_url=stream_url)

    async def request_intercom(
        self, command: RequestIntercomCommand, *, uow: VideoUnitOfWork
    ) -> VideoSessionDTO:
        """`POST /video/intercom` (ADR-0036). D5 authorization has already run
        (`purpose="intercom"`) before this is ever called — same posture as
        `request_live_video`.

        **One active intercom session per device (ADR-0036 §2) — checked here, before any
        session is persisted or the relay is ever called.** Talking to a bus is inherently
        exclusive (unlike ordinary video viewing, where multiple simultaneous viewers of the
        same stream is correct) — two operators must never talk over each other. This is the
        first of two independent checks (`services/jt1078`'s own `SessionManager` enforces the
        same invariant a second time, since only that single in-process object can reliably
        serialize a genuine race between two near-simultaneous requests)."""
        async with uow:
            existing = await uow.video_sessions.list_all()
        if any(
            session.device_id == DeviceId(command.device_id)
            and session.purpose == VideoPurpose.INTERCOM
            and session.status in _OPEN_STATUSES
            for session in existing
        ):
            raise ConflictError(
                f"An intercom session is already open for device {command.device_id}."
            )

        async with uow:
            session = VideoSession.request_intercom(
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
                "No VideoProviderPort is bound - see request_live_video's identical message."
            )

        urls = await self._video_provider.start_intercom(
            device_id=command.device_id,
            camera_id=command.camera_id,
            terminal_id=command.terminal_id,
            channel_no=command.channel_no,
            reference=str(session.id),
            audio_codec=command.audio_codec,
        )
        # ADR-0026 §7's same reasoning as request_live_video: no eager activate() here either -
        # status stays REQUESTED until the relay's own VideoSessionActivated event confirms real
        # media is flowing.
        return video_session_to_dto(
            session, stream_url=urls.downlink_url, uplink_url=urls.uplink_url
        )

    async def stop_video_session(
        self, command: StopVideoSessionCommand, *, uow: VideoUnitOfWork
    ) -> VideoSessionDTO:
        """`POST /video/sessions/{id}/stop`. Unlike the two request methods, a missing
        `VideoProviderPort` does not block ending the session locally — `end()` still runs, so a
        control record can always be closed out even if the vendor-side teardown itself could
        not be attempted.

        **Idempotent on the provider-facing side too (stale-permission fix, focused D5 review
        2026-08-13).** A session already `ENDED`/`FAILED` short-circuits *before* any
        `VideoProviderPort.stop` call — `VideoSession.end()`'s own same-state no-op only
        protects the persisted row; without this guard, calling this method twice for the same
        session (a client retry, or `events/subscribers.py`'s revoke-driven cleanup racing an
        already-completed stop — at-least-once delivery, LLD §10.3) would re-signal the relay/
        device a second time for a session that no longer needs tearing down."""
        async with uow:
            session = await self._get_session_or_raise(uow, command.video_session_id)

        if session.status in _TERMINAL_STATUSES:
            return video_session_to_dto(session)

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

    async def list_active_sessions_for_requester(
        self, *, requested_by_user_id: str, purpose: str, uow: VideoUnitOfWork
    ) -> list[VideoSessionDTO]:
        """Stale-permission fix (focused D5 review, 2026-08-13): resolves every `REQUESTED`/
        `ACTIVE` session a given user currently has open for the given `purpose` — the read side
        of `events/subscribers.ParentVideoLiveAccessRevokedProcessor`/
        `ParentVideoPlaybackAccessRevokedProcessor`'s own "find what to stop" step.
        `requested_by_user_id` is a parent's own `user_id` (`VideoSession.requested_by`), never a
        client-supplied id — the caller resolves it from a trusted `Parent` row first.

        Read-only, no state change — the caller is responsible for actually tearing each session
        down via the existing `stop_video_session`, never a second stop mechanism. Filters
        `list_all()` client-side rather than adding a new indexed finder, the same "an unbounded
        worker read doesn't need one" precedent `notifications/events/subscribers.py`'s own
        `student_assignments.list_all()` use already establishes for an analogous cross-cutting
        read — `video_sessions.requested_by` carries no index of its own (Database Design §7.4),
        matching that reasoning exactly."""
        async with uow:
            sessions = await uow.video_sessions.list_all()
        return [
            video_session_to_dto(session)
            for session in sessions
            if str(session.requested_by) == requested_by_user_id
            and session.purpose.value == purpose
            and session.status in _OPEN_STATUSES
        ]

    async def mark_session_active(
        self, command: MarkVideoSessionActiveCommand, *, uow: VideoUnitOfWork
    ) -> None:
        """ADR-0026 §7 — `events/subscribers.py`'s entry point for the relay's own
        `VideoSessionActivated` event. **No-ops (logs, doesn't raise) for an unknown
        `video_session_id`** — mirrors `fleet_device.DeviceApplicationService.
        record_device_seen`'s identical precedent for a broker-driven fact about a session this
        backend didn't necessarily still have a row for (a relay event arriving after the
        session was already torn down some other way is a real, expected race, not an error).
        Returns `None` — no HTTP caller needs a DTO."""
        async with uow:
            session = await uow.video_sessions.get(VideoSessionId(command.video_session_id))
            if session is None:
                logger.info(
                    "video_session_activated_for_unknown_session",
                    extra={"video_session_id": command.video_session_id},
                )
                return
            session.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(session.pull_domain_events())
            await uow.commit()

    async def mark_session_ended(
        self, command: MarkVideoSessionEndedCommand, *, uow: VideoUnitOfWork
    ) -> None:
        """Same shape as `mark_session_active` — the relay's own `VideoSessionEnded` event."""
        async with uow:
            session = await uow.video_sessions.get(VideoSessionId(command.video_session_id))
            if session is None:
                logger.info(
                    "video_session_ended_for_unknown_session",
                    extra={"video_session_id": command.video_session_id},
                )
                return
            session.end(
                clock=self._clock, actor_id=command.actor.user_id, reason=command.reason
            )
            uow.record_events(session.pull_domain_events())
            await uow.commit()

    async def mark_session_failed(
        self, command: MarkVideoSessionFailedCommand, *, uow: VideoUnitOfWork
    ) -> None:
        """Same shape as `mark_session_active` — the relay's own `VideoSessionFailed` event."""
        async with uow:
            session = await uow.video_sessions.get(VideoSessionId(command.video_session_id))
            if session is None:
                logger.info(
                    "video_session_failed_for_unknown_session",
                    extra={"video_session_id": command.video_session_id},
                )
                return
            session.fail(
                clock=self._clock, actor_id=command.actor.user_id, reason=command.reason
            )
            uow.record_events(session.pull_domain_events())
            await uow.commit()

    async def reconcile_stale_intercom_sessions(
        self, *, stale_after_seconds: float, actor_id: str = "system", uow: VideoUnitOfWork
    ) -> int:
        """ADR-0037's own defense-in-depth backstop, scheduled-job entry point (mirrors
        `BillingApplicationService.sweep_expired_subscriptions`'s exact shape). Independent of
        whether the relay's own `VideoSessionActivated`/`Ended`/`Failed` event ever successfully
        arrives and is consumed — the live-found 2026-09-01 incident: a poisoned broker message
        wedged the shared event-consumer pipeline for over an hour, leaving a `REQUESTED`
        intercom session's own correctly-published `VideoSessionFailed` event never processed,
        permanently blocking every other operator's own attempt to talk to that bus (ADR-0036
        §2's one-active-intercom-session-per-device check, working exactly as designed against
        now-stale data).

        **Scoped to `purpose=INTERCOM` only, deliberately** — an ordinary `REQUESTED`/`ACTIVE`
        live/playback session left open by a dead event pipeline is not, by itself, harmful to
        any *other* user the way a stuck intercom session is (many simultaneous viewers of the
        same device is already the correct, unblocked behavior for video) - reconciling those too
        would be solving a problem nothing has actually reported, `.claude/rules/workflow.md`'s
        own "don't design for hypothetical requirements."

        **`stale_after_seconds` must stay well above the relay's own worst-case internal timeout**
        (`services/jt1078/src/session/session_manager.py`'s `ingest_timeout_seconds`/
        `absolute_idle_seconds` defaults) — this is a backstop for when the *primary*, event-
        driven reconciliation path fails to run at all, never a replacement racing to beat it."""
        async with uow:
            now = self._clock.now().replace(tzinfo=None)
            sessions = await uow.video_sessions.list_all()
            reconciled = 0
            for session in sessions:
                if session.purpose != VideoPurpose.INTERCOM:
                    continue
                if session.status not in _OPEN_STATUSES:
                    continue
                reference_time = session.started_at or session.created_at
                age_seconds = (now - reference_time.replace(tzinfo=None)).total_seconds()
                if age_seconds < stale_after_seconds:
                    continue
                session.fail(
                    clock=self._clock, actor_id=actor_id, reason="reconciliation_stale_timeout"
                )
                uow.record_events(session.pull_domain_events())
                reconciled += 1
            if reconciled:
                await uow.commit()
            return reconciled

    @staticmethod
    async def _get_session_or_raise(
        uow: VideoUnitOfWork, video_session_id: str
    ) -> VideoSession:
        session = await uow.video_sessions.get(VideoSessionId(video_session_id))
        if session is None:
            raise NotFoundError(f"VideoSession {video_session_id} not found.")
        return session
