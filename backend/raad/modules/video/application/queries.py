"""Video application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models). Mirrors
`billing.application.queries`'s single-DTO-per-aggregate convention — `VideoSession` has no
embedded child collections needing a lighter list projection.

**`VideoSessionDTO.stream_url` is not sourced from the domain aggregate** — `VideoSession` never
persists it (`domain/entities.py`'s module docstring). It is populated only by
`application/services.py`'s two request-a-stream methods, straight from that call's
`VideoProviderPort` return value, and is `None` on every other read path (e.g.
`get_video_session_by_id`, or `stop_video_session`'s response) — an in-process passthrough
field, not a second source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raad.modules.video.domain.entities import VideoSession


@dataclass(frozen=True)
class GetVideoSessionByIdQuery:
    video_session_id: str


@dataclass(frozen=True)
class GetRecordingSearchQuery:
    """ADR-0044 §2 — reads a recording search's asynchronous result by its own id."""

    search_id: str


@dataclass(frozen=True)
class RecordingSearchDTO:
    """`status` is `"pending"` until the terminal's own `0x1205` answer arrives, then `"ready"`.
    A ready search with an empty `segments` list is a real answer — the device holds nothing for
    that window — and is deliberately distinguishable from still waiting."""

    search_id: str
    device_id: str
    status: str
    #: `None` while pending, so "still waiting for the device" and "the device answered:
    #: nothing" are distinguishable by value and not only by `status` - `()` is the real,
    #: empty answer. The API schema (`api/schemas.RecordingSearchResponse`) carries the same
    #: `null`-vs-`[]` distinction onto the wire.
    segments: tuple["RecordingSegmentDTO", ...] | None = None


@dataclass(frozen=True)
class RecordingSegmentDTO:
    channel_no: int
    start_time: datetime
    end_time: datetime
    alarm_flag: int
    resource_type: int
    stream_type: int
    storage_type: int
    size_bytes: int


@dataclass(frozen=True)
class VideoSessionDTO:
    id: str
    organization_id: str
    device_id: str
    camera_id: str
    purpose: str
    requested_by: str
    window_start: datetime | None
    window_end: datetime | None
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    stream_url: str | None = None
    #: ADR-0036 — the intercom uplink URL. Same "in-process passthrough, not a second source of
    #: truth" treatment as `stream_url` above: populated only by `request_intercom`'s own
    #: `VideoProviderPort.start_intercom` return value, `None` on every other read path.
    uplink_url: str | None = None


def video_session_to_dto(
    session: VideoSession, *, stream_url: str | None = None, uplink_url: str | None = None
) -> VideoSessionDTO:
    return VideoSessionDTO(
        id=str(session.id),
        organization_id=str(session.organization_id),
        device_id=str(session.device_id),
        camera_id=str(session.camera_id),
        purpose=session.purpose.value,
        requested_by=str(session.requested_by),
        window_start=session.window_start,
        window_end=session.window_end,
        status=session.status.value,
        started_at=session.started_at,
        ended_at=session.ended_at,
        created_at=session.created_at,
        stream_url=stream_url,
        uplink_url=uplink_url,
    )
