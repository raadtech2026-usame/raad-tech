"""HTTP request/response DTOs for `video` (Backend LLD §16; API Contracts §4.5). Pydantic
models are transport-only — no business logic here; `routers.py` does the DTO<->application
translation. Mirrors `billing.api.schemas`'s shape.

Only the three documented `/video/*` routes get a request/response shape here.
`RequestLiveVideoRequest`/`RequestPlaybackVideoRequest` match API Contracts §4.5's documented
bodies verbatim (`{device_id, camera_id}` / `{device_id, camera_id, window_start, window_end}`).
`organization_id` is never a request field on either — see `application/commands.py`'s module
docstring for why.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RequestLiveVideoRequest(BaseModel):
    device_id: str
    camera_id: str
    #: ADR-0043 — optional and additive: omitting it keeps the documented `{device_id,
    #: camera_id}` body and its original main-stream behavior.
    stream_type: Literal["main", "sub"] = Field(
        default="main",
        description=(
            "Terminal encoder stream: `main` (full resolution) or `sub` (low-bitrate preview, "
            "for multi-camera grids)."
        ),
    )


class RequestPlaybackVideoRequest(BaseModel):
    device_id: str
    camera_id: str
    window_start: datetime
    window_end: datetime


class RequestIntercomRequest(BaseModel):
    """`POST /video/intercom` (ADR-0036) — same body shape as `RequestLiveVideoRequest`."""

    device_id: str
    camera_id: str


class VideoSessionResponse(BaseModel):
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
    stream_url: str | None
    #: ADR-0036 — populated only by `POST /video/intercom`'s own response; `None` for every
    #: other route/read path (mirrors `stream_url`'s own established treatment).
    uplink_url: str | None = None


class SearchRecordingsRequest(BaseModel):
    """`POST /video/recordings/search` (ADR-0044 §2). Same `{device_id, camera_id, window_start,
    window_end}` shape as `RequestPlaybackVideoRequest` deliberately — a search is authorized
    against exactly the same device/camera the resulting playback will be, so the two bodies
    stay interchangeable for a client that searches and then plays."""

    device_id: str
    camera_id: str
    window_start: datetime
    window_end: datetime


class RecordingSegmentResponse(BaseModel):
    """One recording the *terminal* reports it holds. Every field is the device's own figure;
    RAAD stores none of this (ADR-0044 §1) — `size_bytes` is shown so an operator can judge a
    segment, never because anything is transferred."""

    channel_no: int
    start_time: datetime
    end_time: datetime
    alarm_flag: int
    resource_type: int
    stream_type: int
    storage_type: int
    size_bytes: int


class RecordingSearchResponse(BaseModel):
    """`status` is `pending` until the terminal answers (ADR-0044 §2) — `segments` is then
    `null`, deliberately distinct from `[]`, which is the device's real answer "nothing
    recorded in that window"."""

    search_id: str
    device_id: str
    status: Literal["pending", "ready"]
    segments: list[RecordingSegmentResponse] | None = None


class PlaybackControlRequest(BaseModel):
    """`POST /video/sessions/{id}/playback-control` (ADR-0044 §4). Named actions, never the
    raw `0x9202` control byte — no protocol number is part of this API's contract.

    `stop` is deliberately absent: `POST /video/sessions/{id}/stop` is the one teardown path,
    so a session can never be half-stopped at the device but still open in RAAD."""

    action: Literal["resume", "pause", "fast_forward", "rewind", "seek", "keyframe_only"]
    #: 1..5 -> 1x/2x/4x/8x/16x (spec Table 6.11); read only for `fast_forward`/`rewind`.
    speed: int = Field(default=1, ge=1, le=5)
    #: Absolute time to jump to; required for `seek`, ignored otherwise.
    position: datetime | None = None
