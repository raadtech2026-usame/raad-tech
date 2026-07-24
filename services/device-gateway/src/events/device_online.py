"""`DeviceOnline` — one of the four device-plane events `.claude/rules/jt808.md` #1 and
`architecture.md` #3 name as this deployable's complete published-event vocabulary. Named in
those rule files and in `session.device_session_manager`'s own `on_device_online` callback since
Phase 9.2, but never previously implemented as a concrete, publishable event — only logged. The
device-gateway Redis integration closes that gap: any vendor adapter's `DeviceSessionManager`
firing `on_device_online` now constructs one of these and publishes it via the shared
`EventPublisher`, exactly like `DevicePositionReported` already does.

Fired on the `AUTHENTICATED -> ONLINE` transition (the first `touch()` after a session is
created) — never on `create()` itself, per `device_session_manager.py`'s own already-resolved
Phase 3.4 §21.1-vs-§3 documentation conflict. `device_id`/`vehicle_id`/`organization_id` are
optional, matching `DeviceSession`'s own optional pass-through typing (unlike
`DevicePositionReported`, where a report is dropped entirely rather than published with a hole —
an online/offline connectivity fact is still meaningful even if enrichment is incomplete).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeviceOnline:
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    event_time: datetime
    received_at: datetime
