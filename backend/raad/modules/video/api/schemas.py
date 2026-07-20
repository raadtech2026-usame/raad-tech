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

from pydantic import BaseModel


class RequestLiveVideoRequest(BaseModel):
    device_id: str
    camera_id: str


class RequestPlaybackVideoRequest(BaseModel):
    device_id: str
    camera_id: str
    window_start: datetime
    window_end: datetime


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
