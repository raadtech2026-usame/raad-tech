"""Subpackaged extended-RTP frame reassembly (spec §6.2.1.1's own `分包处理标记` field —
`extended_rtp.py`'s `subpackage_marker`: 0 atomic, 1 first, 2 last, 3 middle). A single logical
video/audio frame (e.g. one large I-frame) can be split across multiple extended-RTP packets,
each individually under the 950-byte payload ceiling — this reassembler concatenates a
`FIRST -> MIDDLE* -> LAST` run back into one complete frame body before it ever reaches the
repackager (`repackager/flv_muxer.py`), which needs whole frames, not fragments.

**Keyed by `(logical_channel, data_type)`**, not just "the current in-flight sequence" — a real
device may interleave, e.g., atomic audio frames *between* a video I-frame's own fragments on the
same connection; tracking reassembly state per channel+type keeps an audio atomic frame from ever
being mistaken for a fragment of the video sequence in progress, or vice versa.

**A `FIRST` marker abandons and replaces any already-in-progress sequence for that same key** —
a genuinely malformed/lost-frame case (a `LAST` never arrived for the previous sequence), logged
as a dropped-fragment count rather than silently growing a buffer forever or raising and killing
the whole ingest connection over one bad frame (`.claude/rules/jt808.md` #2's "never crash the
connection" discipline, applied here to this deployable's own equivalent situation).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.ingest.extended_rtp import (
    DATA_TYPE_AUDIO,
    SUBPACKAGE_ATOMIC,
    SUBPACKAGE_FIRST,
    SUBPACKAGE_LAST,
    SUBPACKAGE_MIDDLE,
    VIDEO_DATA_TYPES,
    ExtendedRtpFrame,
)


@dataclass(frozen=True)
class ReassembledFrame:
    logical_channel: int
    data_type: int
    timestamp_ms: int | None
    last_i_frame_interval_ms: int | None
    last_frame_interval_ms: int | None
    body: bytes

    @property
    def is_video(self) -> bool:
        return self.data_type in VIDEO_DATA_TYPES

    @property
    def is_audio(self) -> bool:
        return self.data_type == DATA_TYPE_AUDIO


class FrameReassembler:
    def __init__(self) -> None:
        self._in_progress: dict[tuple[int, int], list[ExtendedRtpFrame]] = {}
        self.dropped_sequence_count = 0

    def feed(self, frame: ExtendedRtpFrame) -> ReassembledFrame | None:
        """Returns a complete `ReassembledFrame` the instant a full sequence (or a lone atomic
        frame) is available, else `None` (still buffering fragments)."""
        key = (frame.logical_channel, frame.data_type)

        if frame.subpackage_marker == SUBPACKAGE_ATOMIC:
            return self._finish([frame])

        if frame.subpackage_marker == SUBPACKAGE_FIRST:
            if key in self._in_progress:
                self.dropped_sequence_count += 1
            self._in_progress[key] = [frame]
            return None

        if frame.subpackage_marker == SUBPACKAGE_MIDDLE:
            pending = self._in_progress.get(key)
            if pending is None:
                # A middle fragment with no preceding FIRST - an already-dropped/lost sequence;
                # nothing to append to, discard this fragment rather than starting a new one from
                # the middle (which would produce a corrupt reassembled body).
                return None
            pending.append(frame)
            return None

        if frame.subpackage_marker == SUBPACKAGE_LAST:
            pending = self._in_progress.pop(key, None)
            if pending is None:
                return None
            pending.append(frame)
            return self._finish(pending)

        return None

    def _finish(self, fragments: list[ExtendedRtpFrame]) -> ReassembledFrame:
        first = fragments[0]
        body = b"".join(fragment.body for fragment in fragments)
        return ReassembledFrame(
            logical_channel=first.logical_channel,
            data_type=first.data_type,
            timestamp_ms=first.timestamp_ms,
            last_i_frame_interval_ms=first.last_i_frame_interval_ms,
            last_frame_interval_ms=first.last_frame_interval_ms,
            body=body,
        )
