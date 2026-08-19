"""JT/T 1078 terminal audio/video attribute query (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.1.1/
§6.1.2, ADR-0030). The generic, vendor-agnostic channel-*count* discovery pair — distinct from
`0x9205`/`0x1205` (`video_signaling.py`'s `QueryResourceList`/`ResourceListReport`), which browse
the terminal's own **recorded files**, not its physical channel capability.

Two messages, one direction each:

| Message | Direction | Spec table | Dataclass |
|---|---|---|---|
| `0x9003` query terminal A/V attributes | down (platform -> terminal) | — | (empty body, no dataclass) |
| `0x1003` terminal uploads A/V attributes | up (terminal -> platform) | Table 6.1 | `AvAttributesReport` |

**`0x9003`'s body is empty** ("消息体：空", §6.1.1) — `encode_query_av_attributes()` takes no
arguments and returns `b""`; included as a function (not a bare constant) purely so every command
in this family has a matching `encode_*` entry point, mirroring `video_signaling.py`'s own
per-message-one-function shape.

**`0x1003` is a fixed 10-byte body** (Table 6.1) — no length-prefixed strings, no BCD dates,
unlike every other message in this deployable's video-signaling family. The one field this
deployable's discovery workflow actually needs is `max_video_channels` (offset 9): "终端支持的
最大视频物理通道数量" — the maximum number of video physical channels the terminal supports.
RAAD derives the channel *numbers* (`1..max_video_channels`) itself from this single count,
matching Table 5.31's own confirmed "channels are 1-based, starting at 1" convention — the
terminal does not enumerate individual channels or their semantic meaning (driver-facing,
road-facing, etc.) in this message; that per-channel metadata is a RAAD-side, editable business
concern (ADR-0030), not wire data.

**No correlation field in the body.** Unlike `0x1205` (which echoes the originating `0x9205`'s
serial number inside its own body, per `video_signaling.ResourceListReport.original_serial_no`),
`0x1003`'s body (Table 6.1) carries no such echo — confirmed by reading the table field-by-field,
not assumed. `handlers/av_attributes_handler.py` therefore resolves the pending `0x9003` via
`PendingCommandTracker.resolve_by_terminal_and_message` (matched on `terminal_id`+`message_id`
alone) rather than the standard `(terminal_id, message_id, serial_no)` triple.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.vendors.jt808.protocol.exceptions import MalformedFrameError

_BODY_LENGTH = 10  # Table 6.1's fixed body length


@dataclass(frozen=True)
class AvAttributesReport:
    input_audio_codec: int
    input_audio_channels: int
    input_audio_sample_rate: int
    input_audio_sample_bits: int
    audio_frame_length: int
    supports_audio_output: bool
    video_codec: int
    max_audio_channels: int
    max_video_channels: int


def encode_query_av_attributes() -> bytes:
    """`0x9003` — empty body (§6.1.1: "消息体：空")."""
    return b""


def parse_av_attributes_report(body: bytes) -> AvAttributesReport:
    """`0x1003` — Table 6.1's fixed 10-byte body."""
    if len(body) < _BODY_LENGTH:
        raise MalformedFrameError(
            f"A/V attributes report body shorter than the {_BODY_LENGTH}-byte fixed "
            f"shape ({len(body)} bytes)."
        )
    return AvAttributesReport(
        input_audio_codec=body[0],
        input_audio_channels=body[1],
        input_audio_sample_rate=body[2],
        input_audio_sample_bits=body[3],
        audio_frame_length=int.from_bytes(body[4:6], "big"),
        supports_audio_output=bool(body[6]),
        video_codec=body[7],
        max_audio_channels=body[8],
        max_video_channels=body[9],
    )
