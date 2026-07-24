"""`DeviceOffline` — see `device_online.py`'s module docstring for the shared context (this is
its counterpart). Fired whenever `DeviceSessionManager.close()` runs: idle-timeout sweep expiry,
a dropped transport connection, or graceful shutdown — `reason` distinguishes which
(`"session_expired"`, `"connection_closed"`, `"server_shutdown"`, `"superseded"`-adjacent close
reasons, etc.; not a closed enum, matching `close()`'s own free-text `reason` parameter).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeviceOffline:
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    reason: str
    event_time: datetime
    received_at: datetime
