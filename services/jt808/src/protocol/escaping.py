"""JT/T 808-2013 byte unescaping (§4.4.2). Reverses the escape encoding applied to a raw
frame's header+body+checksum bytes — never the frame delimiter itself; §4.4.2's own scope
statement is "if 0x7e appears in **the checksum, header, or body**", not the delimiter, which
is exactly why Phase 9.1's `FrameBuffer` can correctly scan for delimiters without unescaping
first (its own module docstring already makes this argument; this file is the confirmation
from the primary spec).

Escape rules, verbatim (§4.4.2):
    0x7e <-> 0x7d 0x02
    0x7d <-> 0x7d 0x01

**Ordering, verbatim (§4.4.2):** "发送消息时：消息封装->计算并填充校验码->转义；接收消息时：
转义还原->验证校验码->解析消息" — "When sending: assemble message -> compute and fill checksum
-> escape. When receiving: un-escape -> verify checksum -> parse message." So `unescape()` must
run *before* checksum verification (`checksum.py`) in this phase's parse pipeline
(`parser.py`) — escaping was applied *after* the checksum was computed on the sending side, so
the checksum was never computed over escaped bytes.

**`escape()` (Phase 9.4 addition):** the mirror encode-side operation, needed because JT808
Technical Design §7's Packet Dispatcher "ensures the ack is sent" (the automatic `0x8001`
general response) — genuinely a Dispatcher responsibility per the approved design, not a later
Command Processing (§12) concern, which governs business-initiated downlink commands, not
protocol-level acks. Deliberately not built in Phase 9.3, whose module docstring at the time
said "only the receive path is this phase's job" — that was accurate for a decode-only phase;
Phase 9.4 is the first phase that actually needs to construct outbound bytes.
"""

from __future__ import annotations

from src.protocol.constants import FRAME_DELIMITER
from src.protocol.exceptions import UnescapeError

ESCAPE_MARKER = 0x7D
_ESCAPED_DELIMITER = 0x02  # 0x7d 0x02 -> 0x7e
_ESCAPED_MARKER = 0x01  # 0x7d 0x01 -> 0x7d


def unescape(data: bytes) -> bytes:
    result = bytearray()
    i = 0
    n = len(data)
    while i < n:
        byte = data[i]
        if byte == ESCAPE_MARKER:
            if i + 1 >= n:
                raise UnescapeError("Frame ends with a dangling 0x7d escape marker.")
            next_byte = data[i + 1]
            if next_byte == _ESCAPED_DELIMITER:
                result.append(FRAME_DELIMITER)
            elif next_byte == _ESCAPED_MARKER:
                result.append(ESCAPE_MARKER)
            else:
                raise UnescapeError(
                    f"Invalid escape sequence 0x7d 0x{next_byte:02x} at offset {i}."
                )
            i += 2
        else:
            result.append(byte)
            i += 1
    return bytes(result)


def escape(data: bytes) -> bytes:
    result = bytearray()
    for byte in data:
        if byte == FRAME_DELIMITER:
            result += bytes([ESCAPE_MARKER, _ESCAPED_DELIMITER])
        elif byte == ESCAPE_MARKER:
            result += bytes([ESCAPE_MARKER, _ESCAPED_MARKER])
        else:
            result.append(byte)
    return bytes(result)
