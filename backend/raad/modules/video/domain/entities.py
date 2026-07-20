"""Video domain entities (Backend LLD §5.2; Database Design §7.4). Framework-free — no I/O,
no SQLAlchemy/FastAPI. `VideoSession` is the only aggregate this module builds — Database
Design §7.4 documents exactly one table with a full column list (`video_sessions`);
`playback_requests`, mentioned in the same section, is described only as "follow[ing] the same
shape... for playback-specific tracking" with no distinct column list anywhere in any approved
document — read as descriptive elaboration of `video_sessions.window_start`/`window_end` (this
aggregate already carries both), not a second, separately-schemaed aggregate. Flagged rather
than silently invented.

**No guarded state-machine (`RuleViolationError`) — mirrors `billing.domain.entities.Payment`'s
identical, already-established precedent.** No approved document draws a `video_sessions` state
diagram the way Phase-2 §6.2 draws one for `Trip`; status transitions here are freely settable,
idempotent same-state no-ops, the same "no invented restriction graph" posture `Payment.
mark_processing`'s own docstring already gives for an analogous requested/active/ended/failed
shape.

**No `stream_url`/token field anywhere on this aggregate — deliberately.** Database Design §7.4
lists control metadata only; the actual ephemeral session/port/token state is Redis-owned by the
JT1078 service itself (`.claude/rules/jt1078.md` #2: "only ephemeral session/port/token state
(Redis)... persisted"), never a Business-DB column. Whatever a bound `VideoProviderPort` call
returns is surfaced directly in the API response (`application/services.py`), never persisted
here.

**Event naming, per event, flagged per the same discipline every other module's own event
catalogue already carries:** `VideoSessionStarted`/`VideoSessionEnded` translate the two
documented dot-notation wire events verbatim (JT1078 Technical Design: "Emits
`video.session_started` / `video.session_ended` events for audit") to this codebase's enforced
PascalCase convention — the identical translation `billing.domain.events`'s own docstring applies
to `payment.confirmed`/`payment.failed`. `VideoSessionRequested` (on creation) and
`VideoSessionFailed` (on a failed provider call) have no approved document naming them — this
phase's own choice, mirroring every prior phase's "flagged, not silently assumed" posture for its
own unnamed creation/failure events (e.g. `PaymentInitiated`/`PaymentFailed`).
"""

from __future__ import annotations

from datetime import datetime

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.video.domain import events as video_events
from raad.modules.video.domain.value_objects import (
    CameraId,
    DeviceId,
    OrganizationId,
    UserId,
    VideoPurpose,
    VideoSessionId,
    VideoSessionStatus,
)


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics, duplicated per module deliberately —
    `.claude/rules/backend.md` #1 forbids one module reaching into another's internals, and no
    approved doc calls for a shared-kernel package (identical to every other module's own
    `_AggregateRoot` copy, e.g. `billing.domain.entities._AggregateRoot`)."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class VideoSession(_AggregateRoot):
    """`video_sessions` (Database Design §7.4, "admin-only (D5)"). D5 authorization itself —
    who may call any factory/behavior method below — is enforced entirely outside this
    aggregate (`interfaces/http/policy_guards.enforce_d5`, before any application-service call
    reaches here); this class has no reachable way to know the caller's role and does not
    attempt to re-check it."""

    def __init__(
        self,
        *,
        id: VideoSessionId,
        organization_id: OrganizationId,
        device_id: DeviceId,
        camera_id: CameraId,
        purpose: VideoPurpose,
        requested_by: UserId,
        window_start: datetime | None,
        window_end: datetime | None,
        status: VideoSessionStatus,
        started_at: datetime | None,
        ended_at: datetime | None,
        created_at: datetime,
    ) -> None:
        super().__init__()
        if purpose == VideoPurpose.PLAYBACK:
            if window_start is None or window_end is None:
                raise DomainError(
                    "Playback video sessions require both window_start and window_end."
                )
            if window_end <= window_start:
                raise DomainError("window_end must be after window_start.")
        self.id = id
        self.organization_id = organization_id
        self.device_id = device_id
        self.camera_id = camera_id
        self.purpose = purpose
        self.requested_by = requested_by
        self.window_start = window_start
        self.window_end = window_end
        self.status = status
        self.started_at = started_at
        self.ended_at = ended_at
        self.created_at = created_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, VideoSession) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def request_live(
        cls,
        *,
        id: VideoSessionId,
        organization_id: OrganizationId,
        device_id: DeviceId,
        camera_id: CameraId,
        requested_by: UserId,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "VideoSession":
        """`POST /video/live` (API Contracts §4.5). Starts `REQUESTED`."""
        now = clock.now()
        session = cls(
            id=id,
            organization_id=organization_id,
            device_id=device_id,
            camera_id=camera_id,
            purpose=VideoPurpose.LIVE,
            requested_by=requested_by,
            window_start=None,
            window_end=None,
            status=VideoSessionStatus.REQUESTED,
            started_at=None,
            ended_at=None,
            created_at=now,
        )
        session._record(
            video_events.video_session_requested(
                video_session_id=str(id),
                organization_id=str(organization_id),
                device_id=str(device_id),
                camera_id=str(camera_id),
                purpose=VideoPurpose.LIVE.value,
                requested_by=str(requested_by),
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return session

    @classmethod
    def request_playback(
        cls,
        *,
        id: VideoSessionId,
        organization_id: OrganizationId,
        device_id: DeviceId,
        camera_id: CameraId,
        requested_by: UserId,
        window_start: datetime,
        window_end: datetime,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "VideoSession":
        """`POST /video/playback` (API Contracts §4.5). Starts `REQUESTED`."""
        now = clock.now()
        session = cls(
            id=id,
            organization_id=organization_id,
            device_id=device_id,
            camera_id=camera_id,
            purpose=VideoPurpose.PLAYBACK,
            requested_by=requested_by,
            window_start=window_start,
            window_end=window_end,
            status=VideoSessionStatus.REQUESTED,
            started_at=None,
            ended_at=None,
            created_at=now,
        )
        session._record(
            video_events.video_session_requested(
                video_session_id=str(id),
                organization_id=str(organization_id),
                device_id=str(device_id),
                camera_id=str(camera_id),
                purpose=VideoPurpose.PLAYBACK.value,
                requested_by=str(requested_by),
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return session

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`video.session_started`. Called once a bound `VideoProviderPort` call actually
        succeeds (`application/services.py`). No guarded transition graph — see module
        docstring; idempotent same-state no-op."""
        if self.status == VideoSessionStatus.ACTIVE:
            return
        self.status = VideoSessionStatus.ACTIVE
        self.started_at = clock.now()
        self._record(
            video_events.video_session_started(
                video_session_id=str(self.id),
                organization_id=str(self.organization_id),
                device_id=str(self.device_id),
                camera_id=str(self.camera_id),
                occurred_at=self.started_at,
                actor_id=actor_id,
            )
        )

    def end(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`video.session_ended`. `POST /video/sessions/{id}/stop`. Idempotent same-state
        no-op."""
        if self.status == VideoSessionStatus.ENDED:
            return
        self.status = VideoSessionStatus.ENDED
        self.ended_at = clock.now()
        self._record(
            video_events.video_session_ended(
                video_session_id=str(self.id),
                organization_id=str(self.organization_id),
                device_id=str(self.device_id),
                camera_id=str(self.camera_id),
                occurred_at=self.ended_at,
                actor_id=actor_id,
            )
        )

    def fail(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """No approved document names a failure event — flagged, mirrors `Payment.
        mark_failed`'s identical undocumented-but-analogous treatment. Reachable at this layer
        only; nothing calls it automatically this phase (see `application/services.py`'s module
        docstring for why the provider-call failure path is left to propagate rather than being
        caught here). Idempotent same-state no-op."""
        if self.status == VideoSessionStatus.FAILED:
            return
        self.status = VideoSessionStatus.FAILED
        self._record(
            video_events.video_session_failed(
                video_session_id=str(self.id),
                organization_id=str(self.organization_id),
                device_id=str(self.device_id),
                camera_id=str(self.camera_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
