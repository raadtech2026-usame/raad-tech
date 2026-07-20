"""ORM <-> Domain mapper for `video` (Backend LLD §7.1 "aggregate-in/aggregate-out"; §17 `db`).
Mirrors `billing.infra.mappers`'s `existing=` in-place-update pattern exactly, including its
`_to_naive_utc` fix for every timestamp field that comes from `Clock.now()`.
"""

from __future__ import annotations

from datetime import datetime

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
from raad.modules.video.infra.models import VideoSessionModel


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """See `transport_ops.infra.mappers._to_naive_utc`'s own docstring for the live-DB finding
    that motivated this — identical fix, duplicated per module (`.claude/rules/backend.md` #1)."""
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def video_session_to_model(
    session: VideoSession, *, existing: VideoSessionModel | None = None
) -> VideoSessionModel:
    model = existing if existing is not None else VideoSessionModel(id=str(session.id))
    model.organization_id = str(session.organization_id)
    model.device_id = str(session.device_id)
    model.camera_id = str(session.camera_id)
    model.purpose = session.purpose.value
    model.requested_by = str(session.requested_by)
    model.window_start = _to_naive_utc(session.window_start)
    model.window_end = _to_naive_utc(session.window_end)
    model.status = session.status.value
    model.started_at = _to_naive_utc(session.started_at)
    model.ended_at = _to_naive_utc(session.ended_at)
    model.created_at = _to_naive_utc(session.created_at)
    return model


def model_to_video_session(model: VideoSessionModel) -> VideoSession:
    return VideoSession(
        id=VideoSessionId(model.id),
        organization_id=OrganizationId(model.organization_id),
        device_id=DeviceId(model.device_id),
        camera_id=CameraId(model.camera_id),
        purpose=VideoPurpose(model.purpose),
        requested_by=UserId(model.requested_by),
        window_start=model.window_start,
        window_end=model.window_end,
        status=VideoSessionStatus(model.status),
        started_at=model.started_at,
        ended_at=model.ended_at,
        created_at=model.created_at,
    )
