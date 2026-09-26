"""`DeviceVideoSignalStatusReported` (ADR-0046 §1) — the terminal's own per-channel video-signal
report, from `0x0200` additional items `0x15` (loss) and `0x16` (occlusion).

Published by `handlers/location_handler.py` when the mask changes, on the first report of a
connection, and otherwise at most every few minutes (so the backend's time-limited copy never
expires while the terminal is online). `fleet_device` turns it into each camera's
`video_signal` (`present`/`absent`), which is what decides whether RAAD presents or requests
that camera at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeviceVideoSignalStatusReported:
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    #: Bit n-1 set = logical channel n has no video signal (item `0x15`).
    video_signal_loss_mask: int
    #: Bit n-1 set = logical channel n is occluded (item `0x16`); `None` if not reported.
    video_signal_occlusion_mask: int | None
    event_time: datetime
    received_at: datetime
