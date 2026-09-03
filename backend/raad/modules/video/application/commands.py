"""Video application commands (Backend LLD §4.2 "intent DTOs"). Immutable request objects —
every command carries the calling `Principal` as `actor`, identifiers are plain `str`, mirroring
`billing.application.commands`'s exact shape.

`organization_id` is not accepted from the caller on either request command — it is always
resolved server-side from the referenced `device_id` (`fleet_device`'s own application service,
via `api/routers.py`, never a cross-module DB read) before the command is built, so a caller
cannot claim a different organization than the device actually belongs to.

**`terminal_id`/`channel_no` (JT1078 backend-integration phase)** — likewise resolved server-side
by `api/routers.py` from the same already-loaded `DeviceDTO`/`CameraDTO`, never accepted from the
caller. `VideoApplicationService` threads them straight through to `VideoProviderPort.start_live`/
`start_playback` (`application/ports.py`'s own module docstring has the full reasoning for why
they're resolved once here rather than re-resolved inside the provider adapter).
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
    terminal_id: str
    channel_no: int
    actor: Principal
    #: The device's own real `AudioCapability.codec` (ADR-0033/the G.711A audio fix), threaded
    #: through to `VideoProviderPort.start_live` so the relay can decide, per-session, whether it
    #: has a real decoder for this exact codec - never guessed here or downstream.
    audio_codec: int | None = None


@dataclass(frozen=True)
class RequestPlaybackVideoCommand:
    """`POST /video/playback` (API Contracts §4.5, documented body: `{device_id, camera_id,
    window_start, window_end}`)."""

    organization_id: str
    device_id: str
    camera_id: str
    terminal_id: str
    channel_no: int
    window_start: datetime
    window_end: datetime
    actor: Principal
    audio_codec: int | None = None


@dataclass(frozen=True)
class RequestIntercomCommand:
    """`POST /video/intercom` (ADR-0036). Mirrors `RequestLiveVideoCommand` exactly — no
    `window_start`/`window_end`, same as live."""

    organization_id: str
    device_id: str
    camera_id: str
    terminal_id: str
    channel_no: int
    actor: Principal
    audio_codec: int | None = None


@dataclass(frozen=True)
class StopVideoSessionCommand:
    """`POST /video/sessions/{id}/stop` (API Contracts §4.5, "teardown")."""

    video_session_id: str
    actor: Principal


@dataclass(frozen=True)
class MarkVideoSessionActiveCommand:
    """ADR-0026 §7 — the relay's own `VideoSessionActivated` event, consumed by
    `events/subscribers.py`. `actor` follows `fleet_device/events/subscribers.py`'s own
    `SYSTEM_PRINCIPAL` precedent for a broker-driven, non-HTTP caller."""

    video_session_id: str
    actor: Principal


@dataclass(frozen=True)
class MarkVideoSessionEndedCommand:
    """ADR-0026 §7 — the relay's own `VideoSessionEnded` event. `reason` mirrors that event's
    own field verbatim (e.g. `"viewer_idle_timeout"`)."""

    video_session_id: str
    reason: str | None
    actor: Principal


@dataclass(frozen=True)
class MarkVideoSessionFailedCommand:
    """ADR-0026 §7 — the relay's own `VideoSessionFailed` event."""

    video_session_id: str
    reason: str | None
    actor: Principal
