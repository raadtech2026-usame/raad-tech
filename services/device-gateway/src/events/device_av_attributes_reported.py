"""`DeviceAvAttributesReported` — published by `handlers/av_attributes_handler.py` when a
terminal replies to a `QUERY_AV_ATTRIBUTES` (`0x9003`) command with its own `0x1003` audio/video
attributes report (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.1.2 Table 6.1, ADR-0030). Carries only
`max_video_channels`/`max_audio_channels` (the two fields RAAD's automatic camera-discovery
workflow actually consumes) plus the identity/correlation fields every event in this deployable's
vocabulary already carries — not the full audio-codec/sample-rate detail Table 6.1 also reports,
since no approved use-case reads those yet (`commands/av_attributes.AvAttributesReport` itself
still parses the full body; this event is a deliberate narrower projection of it, the same
"publish only what a real consumer needs" discipline `DevicePositionReported` already applies
relative to `0x0200`'s own full parsed body).
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
    event_time: datetime
    received_at: datetime
