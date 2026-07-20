"""Unit tests for `tracking.infra.adapters.RedisLatestPositionPort` (Backend Stabilization
phase). Stdlib `unittest` — no `pytest` (not an approved dependency). A minimal fake standing
in for `redis.asyncio.Redis` (only the one method the adapter actually calls, `get`) — no real
Redis connection, mirroring how `FakePaymentProvider`/`FakeVideoProvider` fake their own
external ports elsewhere in this suite.

Covers: the documented `vehicle:{id}:last` key shape, the JSON payload -> `VehiclePosition`
field mapping (including the `lat`/`lng` -> `GeoPoint` rename and nullable optional fields), the
"no key -> None" (no known live position) case, and that `id`/`received_at` are synthesized at
read time, never taken from the payload (`infra/adapters.py`'s own module docstring).
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from raad.core.ids.generator import IdGenerator
from raad.core.time.clock import Clock
from raad.modules.tracking.domain.value_objects import VehicleId
from raad.modules.tracking.infra.adapters import RedisLatestPositionPort

VALID_VEHICLE_REF = "some-opaque-vehicle-ref"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc))


class SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


class FakeRedis:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}
        self.get_calls: list[str] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self._values.get(key)


def make_port(redis: FakeRedis) -> RedisLatestPositionPort:
    return RedisLatestPositionPort(
        redis, clock=CLOCK, id_generator=SequentialIdGenerator()
    )


class RedisLatestPositionPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_returns_none(self) -> None:
        redis = FakeRedis()
        port = make_port(redis)
        result = await port.get_latest(VehicleId(VALID_VEHICLE_REF))
        self.assertIsNone(result)
        self.assertEqual(redis.get_calls, [f"vehicle:{VALID_VEHICLE_REF}:last"])

    async def test_full_payload_maps_to_vehicle_position(self) -> None:
        payload = {
            "organization_id": "org-ref-1",
            "vehicle_id": VALID_VEHICLE_REF,
            "device_id": "device-ref-1",
            "trip_id": "trip-ref-1",
            "lat": 2.0469,
            "lng": 45.3182,
            "speed_kph": 42,
            "heading_deg": 180,
            "alarm_flags": 0,
            "event_time": "2026-07-21T07:59:00",
            "is_backfill": False,
        }
        redis = FakeRedis({f"vehicle:{VALID_VEHICLE_REF}:last": json.dumps(payload)})
        port = make_port(redis)

        position = await port.get_latest(VehicleId(VALID_VEHICLE_REF))

        self.assertIsNotNone(position)
        self.assertEqual(str(position.organization_id), "org-ref-1")
        self.assertEqual(str(position.vehicle_id), VALID_VEHICLE_REF)
        self.assertEqual(str(position.device_id), "device-ref-1")
        self.assertEqual(str(position.trip_id), "trip-ref-1")
        self.assertEqual(position.position.latitude, 2.0469)
        self.assertEqual(position.position.longitude, 45.3182)
        self.assertEqual(position.speed_kph.value, 42)
        self.assertEqual(position.heading_deg.value, 180)
        self.assertEqual(position.alarm_flags.value, 0)
        self.assertEqual(position.event_time, datetime(2026, 7, 21, 7, 59, 0))
        self.assertFalse(position.is_backfill)

    async def test_minimal_payload_with_no_trip_or_optional_fields(self) -> None:
        payload = {
            "organization_id": "org-ref-2",
            "vehicle_id": VALID_VEHICLE_REF,
            "device_id": "device-ref-2",
            "trip_id": None,
            "lat": 2.0469,
            "lng": 45.3182,
            "speed_kph": None,
            "heading_deg": None,
            "alarm_flags": None,
            "event_time": "2026-07-21T07:59:00",
            "is_backfill": True,
        }
        redis = FakeRedis({f"vehicle:{VALID_VEHICLE_REF}:last": json.dumps(payload)})
        port = make_port(redis)

        position = await port.get_latest(VehicleId(VALID_VEHICLE_REF))

        self.assertIsNone(position.trip_id)
        self.assertIsNone(position.speed_kph)
        self.assertIsNone(position.heading_deg)
        self.assertIsNone(position.alarm_flags)
        self.assertTrue(position.is_backfill)

    async def test_id_and_received_at_are_synthesized_not_from_payload(self) -> None:
        payload = {
            "organization_id": "org-ref-3",
            "vehicle_id": VALID_VEHICLE_REF,
            "device_id": "device-ref-3",
            "trip_id": None,
            "lat": 2.0469,
            "lng": 45.3182,
            "speed_kph": None,
            "heading_deg": None,
            "alarm_flags": None,
            "event_time": "2026-07-21T07:59:00",
            "is_backfill": False,
        }
        redis = FakeRedis({f"vehicle:{VALID_VEHICLE_REF}:last": json.dumps(payload)})
        port = make_port(redis)

        position = await port.get_latest(VehicleId(VALID_VEHICLE_REF))

        self.assertEqual(str(position.id), "01J8Z3K9G6X8YV5T4N2R000001")
        self.assertEqual(position.received_at, CLOCK.now())

    async def test_key_is_scoped_per_vehicle(self) -> None:
        other_vehicle = "some-other-vehicle-ref"
        redis = FakeRedis()
        port = make_port(redis)
        await port.get_latest(VehicleId(other_vehicle))
        self.assertEqual(redis.get_calls, [f"vehicle:{other_vehicle}:last"])


if __name__ == "__main__":
    unittest.main()
