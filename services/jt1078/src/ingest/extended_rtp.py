"""JT/T 1078 extended-RTP payload demux — `mdvrdocs/MDVR-808-1078-spec.pdf` §6.2.1.1 Table 6.3
("音视频流及透传数据传输协议负载包格式定义"), the wire format a device streams directly to
this relay's own ingest port once `0x9101`/`0x9201` has told it where to connect (ADR-0024 §1/§6).
Pure struct-level parsing, spec-verified byte-for-byte, no hardware needed to test.

**Base 16-byte header, always present:**

| Offset | Field(s)                    | Type      | Notes |
|--------|------------------------------|-----------|-------|
| 0      | frame header                 | DWORD     | fixed `0x30316364` |
| 4      | V(2 bits)/P(1)/X(1)/CC(4)     | BYTE      | fixed `V=2,P=0,X=0,CC=1` per spec text |
| 5      | M(1 bit)/PT(7 bits)           | BYTE      | M = complete-frame-boundary flag; PT = payload type, Table 6.21 |
| 6      | packet sequence               | WORD      | starts at 0, +1 per RTP-extended packet sent |
| 8      | SIM card number               | BCD[6]    | terminal's own SIM card number |
| 14     | logical channel               | BYTE      | Table 5.31 |
| 15     | data type(4 bits)/subpkg(4)   | BYTE      | data type: 0=I-frame,1=P-frame,2=B-frame,3=audio,4=passthrough; |
|        |                               |           | subpackage: 0=atomic,1=first,2=last,3=middle |

**Conditional trailer, length depends on `data_type` (spec's own §6.2.1.1 field notes,
verbatim: timestamp "当数据类型为0100时，则没有该字段" — absent only for passthrough;
Last-I-Frame-Interval/Last-Frame-Interval "当数据类型为非视频帧时，则没有该字段" — absent for
anything that isn't a video frame, i.e. audio *and* passthrough):**

| data_type          | trailer before body_length              | header length before body |
|--------------------|-------------------------------------------|---------------------------|
| video (0/1/2)       | timestamp(8) + lastI(2) + lastFrame(2)    | 16 + 12 = 28 |
| audio (3)           | timestamp(8) only                          | 16 + 8 = 24 |
| passthrough (4)     | none                                        | 16 |

then `body_length` (WORD) + `body` (`BYTE[n]`, `n <= 950` per the spec's own stated ceiling).

**Passthrough (`data_type == 4`) is parsed structurally but never produced by this relay's own
callers** — ADR-0024's live/playback scope never requests `0x9101`'s `数据类型=5`（透传，
passthrough) data type, so no caller of this module ever needs to *act* on a passthrough frame;
it is still decoded correctly (not silently misparsed as a shorter video frame) since a real
device could in principle interleave one on the same media connection.

**Byte-order note**: SIM card number is `BCD[6]` (same packed-BCD convention as every other
`BCD[n]` field in this vendor relationship, `device-gateway`'s own `protocol/header.py`) — decoded
here independently (a separate deployable, no shared code, `.claude/rules/architecture.md` #2)
rather than imported from `device-gateway`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

FRAME_HEADER_MAGIC = 0x30316364
_BASE_HEADER_LENGTH = 16
_MAX_BODY_LENGTH = 950

DATA_TYPE_I_FRAME = 0b0000
DATA_TYPE_P_FRAME = 0b0001
DATA_TYPE_B_FRAME = 0b0010
DATA_TYPE_AUDIO = 0b0011
DATA_TYPE_PASSTHROUGH = 0b0100

VIDEO_DATA_TYPES = {DATA_TYPE_I_FRAME, DATA_TYPE_P_FRAME, DATA_TYPE_B_FRAME}

#: JT/T 1078 Table 6.21 payload type for G.711A. Wire-confirmed 2026-09-03 against the physical
#: `LSZ-C5804DG-Q-F`: 23,544 device-originated audio frames all carried `M/PT = 0x86` (M=1,
#: PT=6), and the same device independently reports `input_audio_codec=6` in its own `0x1003`
#: A/V-attributes reply — two independent observations of the same table agreeing. Video frames
#: from the same device carry PT=98 (H.264), so this field genuinely identifies the codec rather
#: than being decorative.
PAYLOAD_TYPE_G711A = 6

SUBPACKAGE_ATOMIC = 0b0000
SUBPACKAGE_FIRST = 0b0001
SUBPACKAGE_LAST = 0b0010
SUBPACKAGE_MIDDLE = 0b0011


class MalformedExtendedRtpFrameError(Exception):
    """Mirrors `device-gateway`'s own `MalformedFrameError` naming/intent for this deployable's
    own wire format — a frame that cannot be parsed at all (bad magic, truncated header)."""


def _decode_bcd_sim_card(data: bytes) -> str:
    digits = []
    for byte in data:
        high, low = (byte >> 4) & 0x0F, byte & 0x0F
        if high > 9 or low > 9:
            raise MalformedExtendedRtpFrameError(
                f"Invalid BCD nibble in SIM card number byte 0x{byte:02x}."
            )
        digits.append(high)
        digits.append(low)
    return "".join(str(d) for d in digits)


@dataclass(frozen=True)
class ExtendedRtpFrame:
    packet_sequence: int
    sim_card_number: str
    logical_channel: int
    data_type: int
    subpackage_marker: int
    timestamp_ms: int | None  # None only for passthrough
    last_i_frame_interval_ms: int | None  # None for audio/passthrough
    last_frame_interval_ms: int | None  # None for audio/passthrough
    body: bytes
    #: Byte 5's own two fields, parsed since 2026-09-03. Previously this byte was skipped
    #: entirely, which is precisely why a real uplink defect went unnoticed for so long: with no
    #: code reading `payload_type`, nothing could observe that the device sends PT=6 for its own
    #: G.711A audio while this relay's `encode_audio_frame` was hardcoding PT=0 in the reverse
    #: direction. Defaulted so every existing constructor/test keeps working unchanged.
    payload_type: int = 0
    marker: bool = False

    @property
    def is_video(self) -> bool:
        return self.data_type in VIDEO_DATA_TYPES

    @property
    def is_audio(self) -> bool:
        return self.data_type == DATA_TYPE_AUDIO

    @property
    def is_atomic(self) -> bool:
        return self.subpackage_marker == SUBPACKAGE_ATOMIC


def parse_one_frame(buffer: bytes) -> tuple[ExtendedRtpFrame, int] | None:
    """Parses exactly one extended-RTP packet from the *start* of `buffer`. Returns `(frame,
    bytes_consumed)`, or `None` if `buffer` does not yet contain a complete frame (the caller,
    `ExtendedRtpStreamDemuxer`, keeps buffering). Raises `MalformedExtendedRtpFrameError` only for
    genuinely unrecoverable input (bad magic) — a merely-incomplete buffer is `None`, never an
    error, mirroring `device-gateway`'s own "awaiting more subpackages -> `None`, not an
    exception" convention (`protocol/parser.py`)."""
    if len(buffer) < _BASE_HEADER_LENGTH:
        return None

    magic = int.from_bytes(buffer[0:4], "big")
    if magic != FRAME_HEADER_MAGIC:
        raise MalformedExtendedRtpFrameError(
            f"Expected frame header 0x{FRAME_HEADER_MAGIC:08x}, got 0x{magic:08x}."
        )

    m_pt = buffer[5]
    marker = bool(m_pt & 0x80)
    payload_type = m_pt & 0x7F
    packet_sequence = int.from_bytes(buffer[6:8], "big")
    sim_card_number = _decode_bcd_sim_card(buffer[8:14])
    logical_channel = buffer[14]
    type_byte = buffer[15]
    data_type = (type_byte >> 4) & 0x0F
    subpackage_marker = type_byte & 0x0F

    offset = _BASE_HEADER_LENGTH
    timestamp_ms: int | None = None
    last_i_frame_interval_ms: int | None = None
    last_frame_interval_ms: int | None = None

    if data_type != DATA_TYPE_PASSTHROUGH:
        if len(buffer) < offset + 8:
            return None
        timestamp_ms = int.from_bytes(buffer[offset : offset + 8], "big")
        offset += 8
        if data_type in VIDEO_DATA_TYPES:
            if len(buffer) < offset + 4:
                return None
            last_i_frame_interval_ms = int.from_bytes(buffer[offset : offset + 2], "big")
            last_frame_interval_ms = int.from_bytes(
                buffer[offset + 2 : offset + 4], "big"
            )
            offset += 4

    if len(buffer) < offset + 2:
        return None
    body_length = int.from_bytes(buffer[offset : offset + 2], "big")
    offset += 2
    if body_length > _MAX_BODY_LENGTH:
        raise MalformedExtendedRtpFrameError(
            f"Declared body_length {body_length} exceeds the {_MAX_BODY_LENGTH}-byte "
            "protocol ceiling."
        )
    if len(buffer) < offset + body_length:
        return None
    body = buffer[offset : offset + body_length]
    offset += body_length

    frame = ExtendedRtpFrame(
        packet_sequence=packet_sequence,
        sim_card_number=sim_card_number,
        logical_channel=logical_channel,
        data_type=data_type,
        subpackage_marker=subpackage_marker,
        timestamp_ms=timestamp_ms,
        last_i_frame_interval_ms=last_i_frame_interval_ms,
        last_frame_interval_ms=last_frame_interval_ms,
        body=body,
        payload_type=payload_type,
        marker=marker,
    )
    return frame, offset


def _encode_bcd_sim_card(sim_card_number: str) -> bytes:
    """Reverse of `_decode_bcd_sim_card` — packs a 12-digit SIM/terminal-id-tail string into
    `BCD[6]`. `sim_card_number` must be exactly 12 digits (right-padded/truncated by the caller,
    `session/uplink_registry.py`, from the device's own reported value on ingest correlation —
    the same width convention `session/session_manager.py`'s own
    `_terminal_id_matches_sim_card_number` already establishes for this vendor relationship)."""
    if len(sim_card_number) != 12 or not sim_card_number.isdigit():
        raise MalformedExtendedRtpFrameError(
            f"SIM card number for encoding must be exactly 12 digits, got {sim_card_number!r}."
        )
    return bytes(
        (int(sim_card_number[i]) << 4) | int(sim_card_number[i + 1])
        for i in range(0, 12, 2)
    )


def encode_audio_frame(
    *,
    sim_card_number: str,
    logical_channel: int,
    packet_sequence: int,
    body: bytes,
    payload_type: int = PAYLOAD_TYPE_G711A,
) -> bytes:
    """Encodes one atomic (unfragmented) audio extended-RTP frame (ADR-0036) — the reverse of
    `parse_one_frame`'s audio branch, for the relay's own new uplink path (operator mic audio ->
    device). Always `subpackage_marker=SUBPACKAGE_ATOMIC` — the relay never fragments an uplink
    audio frame (each is already well under the 950-byte ceiling: a G.711A frame is 320 bytes,
    ADR-0033). `M` (frame-boundary flag) is always set (a complete, atomic frame). `timestamp_ms`
    is the encoding wall-clock time in milliseconds since epoch, mod 2**64 — the device's own
    receive-side handling of this field for an *inbound* (to it) frame is not documented; this
    mirrors the same field width/semantics `parse_one_frame` already decodes for the identical
    position in a device-originated frame, the most defensible choice absent a spec section that
    describes this direction explicitly."""
    if len(body) > _MAX_BODY_LENGTH:
        raise MalformedExtendedRtpFrameError(
            f"Audio frame body ({len(body)} bytes) exceeds the {_MAX_BODY_LENGTH}-byte "
            "protocol ceiling."
        )
    magic = FRAME_HEADER_MAGIC.to_bytes(4, "big")
    vpxcc = bytes([0b10000001])  # V=2, P=0, X=0, CC=1 (spec text, §6.2.1.1)
    # M=1 (complete frame) | PT (Table 6.21 codec id). **PT was hardcoded to 0 until 2026-09-03**,
    # with a comment calling it "opaque here, informational only" - that was wrong. PT identifies
    # the codec, and the device's own audio frames carry PT=6 for the very same G.711A payload
    # this relay sends back (see `PAYLOAD_TYPE_G711A`). Wire-captured proof of the old behaviour:
    # 712 uplink frames, every one with `M/PT = 0x80`.
    m_pt = bytes([0b10000000 | (payload_type & 0x7F)])
    seq = (packet_sequence & 0xFFFF).to_bytes(2, "big")
    sim = _encode_bcd_sim_card(sim_card_number)
    channel = bytes([logical_channel])
    type_byte = bytes([(DATA_TYPE_AUDIO << 4) | SUBPACKAGE_ATOMIC])
    timestamp = (int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")
    body_length = len(body).to_bytes(2, "big")
    return magic + vpxcc + m_pt + seq + sim + channel + type_byte + timestamp + body_length + body


class ExtendedRtpStreamDemuxer:
    """Incremental TCP-stream framer, mirroring `device-gateway`'s own `protocol/framing.
    FrameBuffer` shape (`feed()` accumulates bytes, returns every complete frame now parseable
    from the front of the buffer, keeps any trailing partial frame buffered for the next
    `feed()` call). TCP carries no message boundaries of its own — an extended-RTP packet may
    arrive split across multiple `recv()` calls, or several may arrive coalesced in one."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[ExtendedRtpFrame]:
        self._buffer.extend(data)
        frames: list[ExtendedRtpFrame] = []
        while True:
            result = parse_one_frame(bytes(self._buffer))
            if result is None:
                break
            frame, consumed = result
            frames.append(frame)
            del self._buffer[:consumed]
        return frames

    @property
    def buffered_byte_count(self) -> int:
        return len(self._buffer)
