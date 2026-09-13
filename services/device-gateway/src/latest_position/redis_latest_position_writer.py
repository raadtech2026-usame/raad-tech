"""`RedisLatestPositionWriter` — the real, Redis-backed `LatestPositionWriter` implementation
(`docs/architecture/post-f7-production-readiness-roadmap.md` Phase A item A2). See `writer_port.
py`'s module docstring for the port's ownership/architecture rationale.

**Wire contract — deliberately byte-exact with `backend/raad/modules/tracking/infra/adapters.
RedisLatestPositionPort.get_latest`'s own parser**, even though these are two separate deployables
with no shared Python code: key `vehicle:{vehicle_id}:last`, value a JSON object with exactly the
fields that adapter's docstring already specifies (JT808 Technical Design §21.1's canonical
`PositionReport` shape) — `organization_id`, `vehicle_id`, `device_id`, `trip_id` (nullable),
`lat`/`lng` (the doc's own abbreviated names, **not** `latitude`/`longitude` — the Business API
side parses these exact keys), `speed_kph`, `heading_deg`, `alarm_flags`, `event_time` (ISO-8601
string), `is_backfill`. `to_snapshot_payload` is a pure function specifically so this contract can
be unit-tested in isolation from any real Redis connection, and so a future JT808 adapter reuses it
verbatim instead of re-deriving the shape from memory.

**Backfilled positions never update this key** — matching `.claude/rules/jt808.md` #3 ("live views
must only use `event_time ≈ now` so stale buffered data never corrupts the live map") and Phase 2
§22.2's identical "backfilled points are excluded... to prevent false historical triggers" rule
applied here to the live snapshot specifically: a late/buffered position landing in Postgres via
`record_backfill_position` must never overwrite a fresher live reading already sitting in Redis.
The LSZ vendor publishes no backfill events today (no `0x0704`-equivalent handler exists), so this
guard is currently unreachable in production — kept anyway since `DevicePositionReported.
is_backfill` is already part of the event this writer receives, and silently omitting the guard
now would be a live bug the instant buffered-data support is ever added.

**Fix-invalid positions never update this key either (root-cause fix — RAAD Live Tracking
wrong-location investigation).** `DevicePositionReported.is_gps_valid` is `False` when the
device itself reported no live GPS fix, or when the resulting coordinate fails `gps_validation.
is_plausible_coordinate` (out-of-range/NaN/Infinity/null-island) — see that event's own module
docstring for the full record of how an un-gated write here let a stale/implausible reading (for
this vendor's hardware, a cached factory coordinate in Shenzhen, China) reach the "current
position" every reader of this key treats as ground truth. Skipping the write, rather than
writing the fix-invalid position anyway, is deliberate: `vehicle:{id}:last` is defined as "the
current live position," and the single most useful thing this cache can do when a report is not
trustworthy is nothing — leave the last genuinely valid position in place rather than replace it
with a worse answer. The raw report is never lost either way: it is still published via
`event_publisher` and persisted by the Business API's `vehicle_positions` history table
(`tracking.domain.entities.VehiclePosition.is_gps_valid`), flagged, for audit/debugging.

**Requires a `decode_responses=True` client** — same requirement and same reasoning as
`RedisEventPublisher`'s own docstring (this class passes/reads plain `str`).
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from src.events.device_position_reported import DevicePositionReported
from src.latest_position.writer_port import LatestPositionWriter


def _key(vehicle_id: str) -> str:
    return f"vehicle:{vehicle_id}:last"


def to_snapshot_payload(event: DevicePositionReported) -> dict[str, Any]:
    """Pure — see module docstring for why this is split out from `write()`. `is_gps_valid` is
    always `true` on anything this writer actually persists (see `write()`'s own gate) — carried
    in the payload anyway so the Business API's parser (`tracking.infra.adapters.
    RedisLatestPositionPort._parse`) never has to guess a default for a field this wire contract
    documents explicitly."""
    return {
        "organization_id": event.organization_id,
        "vehicle_id": event.vehicle_id,
        "device_id": event.device_id,
        "trip_id": event.trip_id,
        "lat": event.latitude,
        "lng": event.longitude,
        "speed_kph": event.speed_kph,
        "heading_deg": event.heading_deg,
        "alarm_flags": event.alarm_flags,
        "event_time": event.event_time.isoformat(),
        "is_backfill": event.is_backfill,
        "is_gps_valid": event.is_gps_valid,
    }


class RedisLatestPositionWriter(LatestPositionWriter):
    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def write(self, event: DevicePositionReported) -> None:
        if event.is_backfill:
            return
        if not event.is_gps_valid:
            return
        await self._redis.set(_key(event.vehicle_id), json.dumps(to_snapshot_payload(event)))
