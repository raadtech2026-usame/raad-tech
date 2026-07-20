"""Video application commands (Backend LLD §4.2 "intent DTOs"). Immutable request objects —
every command carries the calling `Principal` as `actor`, identifiers are plain `str`, mirroring
`billing.application.commands`'s exact shape.

`organization_id` is not accepted from the caller on either request command — it is always
resolved server-side from the referenced `device_id` (`fleet_device`'s own application service,
via `api/routers.py`, never a cross-module DB read) before the command is built, so a caller
cannot claim a different organization than the device actually belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raad.core.tenancy.principal import Principal


@dataclass(frozen=True)
class RequestLiveVideoCommand:
    """`POST /video/live` (API Contracts §4.5, documented body: `{device_id, camera_id}`)."""

    organization_id: str
    device_id: str
    camera_id: str
    actor: Principal


@dataclass(frozen=True)
class RequestPlaybackVideoCommand:
    """`POST /video/playback` (API Contracts §4.5, documented body: `{device_id, camera_id,
    window_start, window_end}`)."""

    organization_id: str
    device_id: str
    camera_id: str
    window_start: datetime
    window_end: datetime
    actor: Principal


@dataclass(frozen=True)
class StopVideoSessionCommand:
    """`POST /video/sessions/{id}/stop` (API Contracts §4.5, "teardown")."""

    video_session_id: str
    actor: Principal
