"""`LatestPositionPort` concrete implementation (Backend Stabilization phase). Database Design
§7.1: "Latest position is NOT read from here [the `vehicle_positions` history table]" — the
current position lives in Redis, keyed `vehicle:{id}:last` (JT808 Technical Design §14/§21.2:
`J->>R: SET vehicle:{id}:last`).

**Read-only, deliberately — no write method on this adapter.** The JT808 Technical Design is
explicit about *who* writes this key: the JT808 device-plane service itself, on every accepted
`0x0200` location report, *before* it even publishes `device.position_reported` to the broker
(§21.2's own sequence diagram: `J->>R: SET vehicle:{id}:last` happens before `J->>B:
device.position_reported`). `.claude/rules/architecture.md` #2/#3 ("FastAPI never terminates a
device socket"; "device plane communicates with the business plane exclusively through
asynchronous domain events") already establishes JT808 as a separate deployable whose native
implementation is out of scope for this codebase (mirrors `video`'s identical "no native JT1078"
posture, `raad/modules/video/application/ports.py`'s own docstring). `TrackingApplicationService.
record_vehicle_position` therefore does **not** also write to Redis — doing so would duplicate a
write JT808 already owns, and would silently invent a second writer for state design already
assigns to exactly one owner. In this environment (no JT808 deployment), `get_latest` will
correctly return `None` for every vehicle — an honest "no live position known" answer, not a
bug — until a real JT808 node (or a test/ops script standing in for one) starts populating the
key.

**Payload format — a necessary, flagged choice.** Neither the JT808 Technical Design nor
Database Design specifies a serialization for the `vehicle:{id}:last` value, only the canonical
field set (§21.1: `PositionReport { organization_id, vehicle_id, device_id, trip_id?, lat, lng,
speed_kph, heading_deg, alarm_flags, event_time, is_backfill }`). This adapter expects a JSON
object with exactly those field names (`lat`/`lng` instead of `latitude`/`longitude`, matching
the doc's own abbreviated names) as the key's string value — human-inspectable, and the same
encoding this codebase already uses for JSON-shaped payloads elsewhere (`outbox.payload_json`,
`audit_entries.metadata_json`). `VehiclePosition.id`/`received_at` are **not** part of that
canonical shape and are synthesized at read time (a fresh ULID; `received_at=clock.now()`) —
`vehicle:{id}:last` is explicitly "reconstructable hot state" (JT808 Technical Design §14), never
a row with its own durable identity the way a `vehicle_positions` history record has one.
"""

from __future__ import annotations

import json
from datetime import datetime

from redis.asyncio import Redis

from raad.core.ids.generator import IdGenerator
from raad.core.time.clock import Clock
from raad.modules.tracking.application.ports import LatestPositionPort
from raad.modules.tracking.domain.entities import VehiclePosition
from raad.modules.tracking.domain.value_objects import (
    AlarmFlags,
    DeviceId,
    GeoPoint,
    HeadingDegrees,
    OrganizationId,
    SpeedKph,
    TripId,
    VehicleId,
    VehiclePositionId,
)


def _key(vehicle_id: VehicleId) -> str:
    return f"vehicle:{vehicle_id}:last"


class RedisLatestPositionPort(LatestPositionPort):
    def __init__(
        self, redis_client: Redis, *, clock: Clock, id_generator: IdGenerator
    ) -> None:
        self._redis = redis_client
        self._clock = clock
        self._id_generator = id_generator

    async def get_latest(self, vehicle_id: VehicleId) -> VehiclePosition | None:
        raw = await self._redis.get(_key(vehicle_id))
        if raw is None:
            return None
        payload = json.loads(raw)
        return VehiclePosition(
            id=VehiclePositionId(self._id_generator.new_id()),
            organization_id=OrganizationId(payload["organization_id"]),
            vehicle_id=VehicleId(payload["vehicle_id"]),
            device_id=DeviceId(payload["device_id"]),
            trip_id=TripId(payload["trip_id"]) if payload.get("trip_id") else None,
            position=GeoPoint(latitude=payload["lat"], longitude=payload["lng"]),
            speed_kph=(
                SpeedKph(payload["speed_kph"])
                if payload.get("speed_kph") is not None
                else None
            ),
            heading_deg=(
                HeadingDegrees(payload["heading_deg"])
                if payload.get("heading_deg") is not None
                else None
            ),
            alarm_flags=(
                AlarmFlags(payload["alarm_flags"])
                if payload.get("alarm_flags") is not None
                else None
            ),
            event_time=_parse_event_time(payload["event_time"]),
            received_at=self._clock.now(),
            is_backfill=bool(payload.get("is_backfill", False)),
        )


def _parse_event_time(value: object) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=None)
    return datetime.fromisoformat(str(value))
