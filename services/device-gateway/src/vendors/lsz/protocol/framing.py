"""LSZ MDVR frame boundary detection — the vendor-protocol equivalent of `src.protocol.framing.
FrameBuffer`, with the same public shape (`feed(data) -> list[bytes]`, `reset()`) so it can be
passed as `connection.Connection`'s injectable `frame_buffer` (ADR-0009) without any other change
to the transport layer.

**Framing strategy — a deliberate, flagged choice, not the only reading of the vendor document.**
Every signaling-channel command in `mdvrdocs/mdvr网络通信协议V0.00.30_150103 - 英文.doc` has the
shape `$$dc<length>,<content...>#`: a `$$dc` start marker, a 4-ASCII-digit content-length field,
comma-separated content, and a trailing `#`. The vendor document states the length field is "the
content length... in bytes" but never precisely defines whether that count includes or excludes
the length field's own comma, the trailing `#`, or where exactly counting starts — and no worked
example in either source document is annotated closely enough to resolve this by inspection
(`docs/vendor/HARDWARE_ANALYSIS.md` §17, limitation #8's sibling gap). Rather than guess at
byte-counting semantics that could silently misframe a real device's traffic, this buffer scans
for the unambiguous `$$dc` ... `#` delimiter pair instead — exactly the same *strategy* `src.
protocol.framing.FrameBuffer` already uses for JT/T 808's `0x7e` delimiter, just with a multi-byte
start marker instead of a single byte. The declared length field is still parsed out by
`parser.py` and can be used there for a sanity-check/mismatch warning, but it is never load-bearing
for framing itself.

**Known limitation, inherited from the vendor's own documentation, not introduced here:** none of
the messages this adapter parses (`V101` registration, `V109` heartbeat, `V114` position, `C100`/
`C501` acks) carry an unbounded free-text field, so a literal `#` byte colliding with content
before the real terminator is not a realistic risk for this adapter's actual scope — but the
vendor protocol defines no escaping mechanism at all, so a message type carrying a genuinely
free-text field (e.g. an alarm description) could in principle contain an embedded `#`. Out of
scope here (this adapter never parses those message types); flagged so a future extension doesn't
rediscover this as a mystery framing bug.

Media-channel frames (`@@$$dc<4-byte-binary-length>...####`, used only for video/file transfer,
B3) are a structurally different framing scheme this buffer does not handle at all — signaling-
channel only, matching this package's own documented scope.
"""

from __future__ import annotations

from src.vendors.lsz.protocol.exceptions import MdvrFrameTooLargeError

_START_MARKER = b"$$dc"
_END_MARKER = b"#"


class MdvrFrameBuffer:
    """Stateful, per-connection incremental frame decoder. Feed raw bytes as they arrive; get
    back zero or more complete raw frames — each the bytes between (and including) `$$dc` and
    the byte immediately before the terminating `#` (the `#` itself is stripped, matching `src.
    protocol.framing.FrameBuffer`'s own "delimiters stripped" convention)."""

    def __init__(self, *, max_frame_size: int) -> None:
        self._max_frame_size = max_frame_size
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buffer.extend(data)
        frames: list[bytes] = []
        while True:
            start = self._buffer.find(_START_MARKER)
            if start == -1:
                self._drop_unbounded_noise()
                break
            end = self._buffer.find(_END_MARKER, start)
            if end == -1:
                self._drop_unbounded_noise()
                break
            frames.append(bytes(self._buffer[start:end]))
            del self._buffer[: end + 1]
        return frames

    def _drop_unbounded_noise(self) -> None:
        """No complete frame is available yet — either no start marker, or a start marker with
        no terminator so far. Bounded the same way `src.protocol.framing.FrameBuffer` bounds an
        unterminated frame: once buffered bytes exceed `max_frame_size` with nothing resolving,
        treat it as a malformed/hostile peer rather than buffering forever."""
        if len(self._buffer) > self._max_frame_size:
            raise MdvrFrameTooLargeError(
                f"Buffered bytes exceed max_frame_size={self._max_frame_size} without a "
                "complete '$$dc'...'#' frame."
            )

    def reset(self) -> None:
        self._buffer = bytearray()
