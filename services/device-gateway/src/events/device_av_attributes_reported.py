"""`DeviceAvAttributesReported` — published by `handlers/av_attributes_handler.py` when a
terminal replies to a `QUERY_AV_ATTRIBUTES` (`0x9003`) command with its own `0x1003` audio/video
attributes report (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.1.2 Table 6.1, ADR-0030).

**Widened by ADR-0033 to carry the full `AvAttributesReport` body, not just
`max_video_channels`/`max_audio_channels`.** Originally a deliberate narrower projection ("no
approved use-case reads those yet," matching `DevicePositionReported`'s own "publish only what a
real consumer needs" discipline) — that was correct when written, but left the terminal's real
audio codec/sample-rate/bit-depth/output-support silently unrecoverable: `commands/
av_attributes.AvAttributesReport` still parsed the full 10-byte body every time, `handlers/
av_attributes_handler.py` still discarded 7 of its 9 fields before this event was even
constructed, so no capture of a real device's audio capability ever existed anywhere past this
handler (confirmed live, 2026-08-27: `av_attributes_requested_at` was already set for the bench
terminal from a 2026-08-19 exchange, but no trace of its audio fields survived). ADR-0033 is the
real consumer this widening exists for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeviceAvAttributesReported:
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    correlation_id: str
    max_video_channels: int
    max_audio_channels: int
    input_audio_codec: int
    input_audio_channels: int
    input_audio_sample_rate: int
    input_audio_sample_bits: int
    audio_frame_length: int
    supports_audio_output: bool
    video_codec: int
    event_time: datetime
    received_at: datetime
