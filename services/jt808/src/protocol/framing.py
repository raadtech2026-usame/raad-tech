"""JT808 frame boundary detection (Phase 9.1 — Transport Layer only; Phase 3.4 §6/§20).

Finds complete frames within a byte stream delimited by `FRAME_DELIMITER` (0x7e) on both
ends, buffering across however many partial TCP reads a frame's bytes arrive in. **Produces
raw, still-escaped frame bytes** (the body between the two delimiters, exactly as received) —
it does not unescape byte-stuffing, verify the checksum, or interpret `message_id`/body
fields. Un-escaping is the first step of *parsing* a frame's content (Phase 3.4 §6's "Packet
Parser"), a later phase's job (explicitly out of this phase's scope) — this layer only knows
where one frame ends and the next begins.

Delimiter-scanning alone is protocol-correct without unescaping first: JT/T 808's escape rule
means a literal `0x7e` byte inside a frame's body is always transmitted as the two-byte
sequence `0x7d 0x02`, never as a bare `0x7e` — so every bare `0x7e` byte in the stream is
genuinely a frame delimiter, never a disguised body byte.
"""

from __future__ import annotations

from src.protocol.constants import FRAME_DELIMITER


class FrameTooLargeError(Exception):
    """Raised when buffered, undelimited bytes exceed `max_frame_size` — a malformed or
    hostile peer sending an unbounded stream without a closing delimiter. The caller
    (`connection/connection.py`) treats this as fatal for that connection."""


class FrameBuffer:
    """Stateful, per-connection incremental frame decoder. Feed raw bytes as they arrive from
    the socket; get back zero or more complete raw frames (delimiters stripped, contents
    unmodified/still-escaped).

    Every delimiter byte both closes the frame in progress (if any bytes were buffered) and
    opens the next one — this correctly handles both a shared delimiter between back-to-back
    frames and two distinct adjacent delimiter bytes, without ever emitting a spurious empty
    frame for the latter case.
    """

    def __init__(self, *, max_frame_size: int) -> None:
        self._max_frame_size = max_frame_size
        self._buffer = bytearray()
        self._in_frame = False

    def feed(self, data: bytes) -> list[bytes]:
        frames: list[bytes] = []
        for byte in data:
            if byte == FRAME_DELIMITER:
                if self._in_frame and self._buffer:
                    frames.append(bytes(self._buffer))
                    self._buffer = bytearray()
                self._in_frame = True
                continue
            if self._in_frame:
                self._buffer.append(byte)
                if len(self._buffer) > self._max_frame_size:
                    raise FrameTooLargeError(
                        f"Buffered frame exceeds max_frame_size={self._max_frame_size} "
                        "bytes without a closing delimiter."
                    )
            # Bytes before the first delimiter are noise (mid-stream connect, garbage) — drop.
        return frames

    def reset(self) -> None:
        self._buffer = bytearray()
        self._in_frame = False
