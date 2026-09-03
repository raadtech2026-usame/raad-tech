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
    #: ADR-0036. Signaled with `0x9101 data_type=2` (not `start_live`'s unchanged `data_type=0`)
    #: and closed with `0x9102 control=4` (not `control=0`) — see `session_manager.py`'s own
    #: `_signal_device_stop`.
    INTERCOM = "intercom"


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
        """Kept for callers that only need the boolean. `idle_reason` (below) is the richer form
        — prefer it wherever the *reason* is reported to anyone, because the two conditions have
        completely different operational meanings."""
        return (
            self.idle_reason(
                viewer_grace_seconds=viewer_grace_seconds,
                absolute_idle_seconds=absolute_idle_seconds,
            )
            is not None
        )

    def idle_reason(
        self, *, viewer_grace_seconds: float, absolute_idle_seconds: float
    ) -> str | None:
        """The two independent, "belt-and-suspenders" idle conditions ADR-0024 §5 point 3
        names — now reported as *distinct* reasons (2026-09-02), because collapsing both into
        the single string `"viewer_idle_timeout"` was actively misleading in diagnosis.

        - `"viewer_idle_timeout"`: genuinely no viewers attached for `viewer_grace_seconds`
          since the last one disconnected. The browser went away.
        - `"ingest_stalled_timeout"`: viewers may well still be attached and waiting — the
          *device* simply stopped sending media for `absolute_idle_seconds`.

        These demand opposite investigations (browser/network vs. device/vendor), and the old
        shared label sent a live investigation down the wrong path: every session in a real
        two-cycle bench test against the physical `LSZ-C5804DG-Q-F` was removed 66-70s after
        its own last keyframe - unambiguously the second condition - while the log said
        "viewer", implying the first."""
        now = time.monotonic()
        if (
            self.viewer_count == 0
            and self.last_viewer_disconnected_at is not None
            and now - self.last_viewer_disconnected_at > viewer_grace_seconds
        ):
            return "viewer_idle_timeout"
        if now - self.last_activity_at > absolute_idle_seconds:
            return "ingest_stalled_timeout"
        return None
