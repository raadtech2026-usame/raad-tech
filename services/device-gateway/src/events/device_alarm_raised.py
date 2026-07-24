"""`DeviceAlarmRaised` — the fourth event `.claude/rules/jt808.md` #1/`architecture.md` #3 name
as this deployable's complete published-event vocabulary. Defined here (shape only) so the
shared `EventPublisher`/Redis publishing machinery is complete and ready — **no vendor adapter
constructs one yet**. Neither JT/T 808's alarm message (`MULTIMEDIA_EVENT_UPLOAD`, still a
no-op `PlaceholderMessageHandler`) nor the LSZ MDVR adapter (registration/heartbeat/position only,
per its own README's documented scope) has a real alarm handler built. Building one is real,
undesigned business logic (which alarm types map to which severity/action, per
`docs/vendor/HARDWARE_INTEGRATION_PLAN.md` §10's own "missing feature, needs a product decision"
finding for the LSZ side) — out of scope for this event-bus/Redis-integration phase specifically,
flagged rather than fabricated. This dataclass exists so that future work is additive (a new
handler calling `EventPublisher.publish(DeviceAlarmRaised(...))`), not a second round of event-bus
plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeviceAlarmRaised:
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    alarm_type: str
    alarm_flags: int
    event_time: datetime
    received_at: datetime
