"""`VideoSession` — the relay's own in-memory session record (ADR-0024 §4/§5). A different
object from the Business API's `backend/raad/modules/video/domain/entities.py` `VideoSession` —
that one is the durable Postgres control-metadata row; this one is the relay's ephemeral,
process-local runtime state for an active/pending session, discarded on teardown, never
persisted anywhere.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class VideoSessionKind(str, Enum):
    LIVE = "live"
    PLAYBACK = "playback"


class VideoSessionState(str, Enum):
    REQUESTED = "requested"  # backend asked for a session; device not yet streaming
    ACTIVE = "active"  # device's media connection is producing frames
    ENDED = "ended"  # torn down cleanly (viewer idle timeout, explicit stop, window exhausted)
    FAILED = "failed"  # device never connected / signaling failed / media channel error


def new_session_id() -> str:
    return uuid.uuid4().hex


@dataclass
class VideoSession:
    session_id: str
    terminal_id: str
    kind: VideoSessionKind
    device_id: str | None
    vehicle_id: str | None
    organization_id: str | None
    correlation_id: str
    logical_channel: int
    #: The device's own real `0x1003`-reported `input_audio_codec` (Table 6.21), if known - the
    #: raw wire byte, never interpreted here. `None` when the caller didn't supply one (an older
    #: backend build, or a device with no captured `AudioCapability` yet, ADR-0033) - `relay.py`'s
    #: own audio-decoder dispatch table treats `None`/any unrecognized value identically: no
    #: audio tags are ever built for that session, matching this codebase's pre-existing
    #: video-only behavior exactly.
    audio_codec: int | None = None
    state: VideoSessionState = VideoSessionState.REQUESTED
    viewer_count: int = 0
    created_at: float = field(default_factory=time.monotonic)
    activated_at: float | None = None
    last_activity_at: float = field(default_factory=time.monotonic)
    last_viewer_disconnected_at: float | None = None

    def touch(self) -> None:
        self.last_activity_at = time.monotonic()

    def activate(self) -> None:
        if self.state == VideoSessionState.REQUESTED:
            self.state = VideoSessionState.ACTIVE
            self.activated_at = time.monotonic()
        self.touch()

    def add_viewer(self) -> None:
        self.viewer_count += 1
        self.last_viewer_disconnected_at = None
        self.touch()

    def remove_viewer(self) -> None:
        self.viewer_count = max(0, self.viewer_count - 1)
        if self.viewer_count == 0:
            self.last_viewer_disconnected_at = time.monotonic()
        self.touch()

    def is_idle_past(self, *, viewer_grace_seconds: float, absolute_idle_seconds: float) -> bool:
        """The two independent, "belt-and-suspenders" idle conditions ADR-0024 §5 point 3
        names: no viewers for `viewer_grace_seconds` since the last one disconnected, OR no
        activity at all (no frame ingested, no viewer event) for `absolute_idle_seconds` —
        the defensive backstop against a viewer-count bookkeeping bug."""
        now = time.monotonic()
        if (
            self.viewer_count == 0
            and self.last_viewer_disconnected_at is not None
            and now - self.last_viewer_disconnected_at > viewer_grace_seconds
        ):
            return True
        if now - self.last_activity_at > absolute_idle_seconds:
            return True
        return False
