"""Session-lifecycle event dataclasses — control-plane facts only, never a media byte."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class VideoSessionActivated:
    session_id: str
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    correlation_id: str
    event_time: datetime


@dataclass(frozen=True)
class VideoSessionEnded:
    session_id: str
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    correlation_id: str
    reason: str  # "viewer_idle_timeout" | "explicit_stop" | "media_channel_dropped" | ...
    event_time: datetime


@dataclass(frozen=True)
class VideoSessionFailed:
    session_id: str
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    correlation_id: str
    reason: str  # "ingest_timeout" | "signaling_failed" | ...
    event_time: datetime
