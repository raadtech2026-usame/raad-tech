"""Unit tests for `tracking.infra.adapters.RedisGeofenceStatePort` (post-F7 roadmap item A5;
ADR-0014). Stdlib `unittest` — no `pytest`. A minimal fake standing in for `redis.asyncio.Redis`
(only `get`/`set`, the two methods this adapter actually calls), mirroring
`test_tracking_redis_latest_position.py`'s own `FakeRedis` convention.

Covers: the `trip:{id}:geofence` key shape, the JSON payload <-> `GeofenceHysteresisState` field
mapping (including defaults for a partial/legacy payload), the "no key -> None" case, and that
`save_state` always sets the documented TTL.
"""

from __future__ import annotations

import json
import unittest

from raad.modules.tracking.application.ports import GeofenceHysteresisState
from raad.modules.tracking.domain.value_objects import TripId
from raad.modules.tracking.infra.adapters import (
    _GEOFENCE_STATE_TTL_SECONDS,
    RedisGeofenceStatePort,
)

VALID_TRIP_REF = "some-opaque-trip-ref"


class FakeRedis:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self._values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.set_calls.append((key, value, ex))
        self._values[key] = value


def make_port(redis: FakeRedis) -> RedisGeofenceStatePort:
    return RedisGeofenceStatePort(redis)


class RedisGeofenceStatePortTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_returns_none(self) -> None:
        redis = FakeRedis()
        port = make_port(redis)
        result = await port.get_state(TripId(VALID_TRIP_REF))
        self.assertIsNone(result)
        self.assertEqual(redis.get_calls, [f"trip:{VALID_TRIP_REF}:geofence"])

    async def test_full_payload_maps_to_hysteresis_state(self) -> None:
        payload = {
            "stop_target_id": "stop-ref-1",
            "stop_is_inside_arrival": True,
            "stop_is_inside_approach": True,
            "org_is_inside": False,
            "last_fired_at": {"entered_stop": "2026-07-26T09:00:00+00:00"},
        }
        redis = FakeRedis({f"trip:{VALID_TRIP_REF}:geofence": json.dumps(payload)})
        port = make_port(redis)

        state = await port.get_state(TripId(VALID_TRIP_REF))

        self.assertIsNotNone(state)
        self.assertEqual(state.stop_target_id, "stop-ref-1")
        self.assertTrue(state.stop_is_inside_arrival)
        self.assertTrue(state.stop_is_inside_approach)
        self.assertFalse(state.org_is_inside)
        self.assertEqual(
            state.last_fired_at, {"entered_stop": "2026-07-26T09:00:00+00:00"}
        )

    async def test_partial_payload_defaults_missing_fields(self) -> None:
        """A payload missing newer fields (e.g. written by an older version of this adapter)
        must not crash - defaults match a brand-new state's own defaults."""
        redis = FakeRedis({f"trip:{VALID_TRIP_REF}:geofence": json.dumps({})})
        port = make_port(redis)

        state = await port.get_state(TripId(VALID_TRIP_REF))

        self.assertIsNone(state.stop_target_id)
        self.assertFalse(state.stop_is_inside_arrival)
        self.assertFalse(state.stop_is_inside_approach)
        self.assertFalse(state.org_is_inside)
        self.assertEqual(state.last_fired_at, {})

    async def test_save_state_writes_expected_key_payload_and_ttl(self) -> None:
        redis = FakeRedis()
        port = make_port(redis)
        state = GeofenceHysteresisState(
            stop_target_id="stop-ref-2",
            stop_is_inside_arrival=True,
            stop_is_inside_approach=True,
            org_is_inside=False,
            last_fired_at={"approaching_stop": "2026-07-26T09:00:00+00:00"},
        )

        await port.save_state(TripId(VALID_TRIP_REF), state)

        self.assertEqual(len(redis.set_calls), 1)
        key, raw, ex = redis.set_calls[0]
        self.assertEqual(key, f"trip:{VALID_TRIP_REF}:geofence")
        self.assertEqual(ex, _GEOFENCE_STATE_TTL_SECONDS)
        self.assertEqual(
            json.loads(raw),
            {
                "stop_target_id": "stop-ref-2",
                "stops_exhausted": False,
                "stop_is_inside_arrival": True,
                "stop_is_inside_approach": True,
                "org_is_inside": False,
                "last_fired_at": {"approaching_stop": "2026-07-26T09:00:00+00:00"},
            },
        )

    async def test_key_is_scoped_per_trip(self) -> None:
        other_trip = "some-other-trip-ref"
        redis = FakeRedis()
        port = make_port(redis)
        await port.get_state(TripId(other_trip))
        self.assertEqual(redis.get_calls, [f"trip:{other_trip}:geofence"])

    async def test_round_trip_through_save_then_get(self) -> None:
        redis = FakeRedis()
        port = make_port(redis)
        state = GeofenceHysteresisState(stop_target_id="stop-ref-3")

        await port.save_state(TripId(VALID_TRIP_REF), state)
        reloaded = await port.get_state(TripId(VALID_TRIP_REF))

        self.assertEqual(reloaded.stop_target_id, "stop-ref-3")
        self.assertFalse(reloaded.stop_is_inside_arrival)


if __name__ == "__main__":
    unittest.main()
