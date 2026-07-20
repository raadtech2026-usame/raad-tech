"""Domain events for the `video` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Mirrors `billing.domain.events`'s exact
`_new_event` factory pattern, duplicated per module for the same reason every other per-module
convention in this codebase is (`.claude/rules/backend.md` #1).

See `entities.py`'s module docstring for the provenance of each event name below —
`VideoSessionStarted`/`VideoSessionEnded` are documented (JT1078 Technical Design's
`video.session_started`/`video.session_ended`, translated to PascalCase);
`VideoSessionRequested`/`VideoSessionFailed` are this phase's own flagged choice.
"""

from __future__ import annotations

from datetime import datetime

from raad.core.events.base import DomainEvent
from raad.core.ids.generator import generate_ulid


def _new_event(
    *,
    event_type: str,
    aggregate_id: str,
    org_id: str,
    occurred_at: datetime,
    payload: dict[str, object],
) -> DomainEvent:
    return DomainEvent(
        event_id=generate_ulid(),
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=org_id,
        correlation_id=None,
        payload=payload,
        aggregate_type="VideoSession",
        aggregate_id=aggregate_id,
    )


def video_session_requested(
    *,
    video_session_id: str,
    organization_id: str,
    device_id: str,
    camera_id: str,
    purpose: str,
    requested_by: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="VideoSessionRequested",
        aggregate_id=video_session_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "device_id": device_id,
            "camera_id": camera_id,
            "purpose": purpose,
            "requested_by": requested_by,
            "actor_id": actor_id,
        },
    )


def video_session_started(
    *,
    video_session_id: str,
    organization_id: str,
    device_id: str,
    camera_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`video.session_started` (JT1078 Technical Design, "Emits ... events for audit")."""
    return _new_event(
        event_type="VideoSessionStarted",
        aggregate_id=video_session_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"device_id": device_id, "camera_id": camera_id, "actor_id": actor_id},
    )


def video_session_ended(
    *,
    video_session_id: str,
    organization_id: str,
    device_id: str,
    camera_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """`video.session_ended` (JT1078 Technical Design, "Emits ... events for audit")."""
    return _new_event(
        event_type="VideoSessionEnded",
        aggregate_id=video_session_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"device_id": device_id, "camera_id": camera_id, "actor_id": actor_id},
    )


def video_session_failed(
    *,
    video_session_id: str,
    organization_id: str,
    device_id: str,
    camera_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="VideoSessionFailed",
        aggregate_id=video_session_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"device_id": device_id, "camera_id": camera_id, "actor_id": actor_id},
    )
