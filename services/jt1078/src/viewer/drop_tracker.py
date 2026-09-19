"""Per-session accounting of media chunks dropped for backpressured viewers (2026-09-19).

`SessionBroadcastHub` drops the oldest queued chunk when a viewer's bounded send queue is full
(`broadcast_hub.py`'s module docstring) and returns the viewers that happened to, but `relay.py`
discarded that return value, so a drop was invisible: the 2026-09-18 production session took in
442 MB from the device and sent 190 MB to viewers with nothing in the logs to say whether frames
were lost on the way. A dropped video chunk can freeze or smear the picture until the next
keyframe, which is exactly what an operator reports as "No signal" or artefacts, so this has to
be visible to tell a relay-side drop from a device-side gap.

Logging is rate-limited per session — the first drop is logged at once, then at most one line
per `log_interval_seconds` carrying the count since the previous line — because drops arrive in
bursts (one per frame while a viewer is behind) and must not flood the log.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from src.logging_setup import get_logger, log_with_fields

logger = get_logger("jt1078.viewer.drop_tracker")

DEFAULT_LOG_INTERVAL_SECONDS = 5.0


@dataclass
class _SessionDrops:
    total: int = 0
    pending: Counter = field(default_factory=Counter)
    last_logged_at: float | None = None


class ViewerDropTracker:
    def __init__(
        self,
        *,
        log_interval_seconds: float = DEFAULT_LOG_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._log_interval_seconds = log_interval_seconds
        self._clock = clock
        self._sessions: dict[str, _SessionDrops] = {}

    def record(self, session_id: str, *, dropped: int, kind: str) -> None:
        """`dropped` is the number of viewers that had to discard an older chunk to make room
        for this one (`len()` of a `broadcast_*` return value); `kind` is `"video"`/`"audio"`."""
        if dropped <= 0:
            return
        stats = self._sessions.setdefault(session_id, _SessionDrops())
        stats.total += dropped
        stats.pending[kind] += dropped
        now = self._clock()
        if stats.last_logged_at is not None and now - stats.last_logged_at < self._log_interval_seconds:
            return
        log_with_fields(
            logger,
            30,
            "viewer_frames_dropped",
            session_id=session_id,
            video_dropped=stats.pending["video"],
            audio_dropped=stats.pending["audio"],
            dropped_total=stats.total,
        )
        stats.pending.clear()
        stats.last_logged_at = now

    def pop_total(self, session_id: str) -> int:
        """Total chunks dropped over the session's life; forgets the session."""
        stats = self._sessions.pop(session_id, None)
        return stats.total if stats is not None else 0
