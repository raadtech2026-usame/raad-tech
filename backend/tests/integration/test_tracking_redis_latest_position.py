"""Redis-backed integration test for `tracking.infra.adapters.RedisLatestPositionPort`
(Backend Stabilization phase). Stdlib `unittest`, mirroring the live-DB integration tests'
skip-guard pattern exactly — but gated on `RAAD_REDIS__URL` instead of `RAAD_DB__URL`.

Covers what `tests/unit/test_tracking_redis_latest_position.py`'s fake-Redis unit tests cannot:
a real `redis.asyncio.Redis.from_url` connection, and a real `SET`/`GET` round trip through the
documented `vehicle:{id}:last` key.

**Requires a reachable Redis** configured via `RAAD_REDIS__URL` (`.env`). Skipped entirely (not
failed) when unavailable — no Redis is reachable in this sandboxed dev environment as of this
phase (confirmed: no `.env` value set, no local `redis-server`/Docker available), so this file
is genuinely deferred rather than silently absent, ready to run unmodified once a real Redis
instance is configured.
"""

from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis

from raad.core.config.settings import get_settings
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.tracking.domain.value_objects import VehicleId
from raad.modules.tracking.infra.adapters import RedisLatestPositionPort


def _redis_available() -> bool:
    try:
        return bool(get_settings().redis.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_REDIS__URL not configured — Redis integration tests require a live instance."


@unittest.skipUnless(_redis_available(), _SKIP_REASON)
class RedisLatestPositionPortIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.redis = Redis.from_url(settings.redis.url, decode_responses=True)
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.vehicle_id = f"vehicle-{uuid.uuid4().hex[:8]}"
        self._key = f"vehicle:{self.vehicle_id}:last"

    async def asyncTearDown(self) -> None:
        await self.redis.delete(self._key)
        await self.redis.aclose()

    async def test_set_then_get_latest_round_trips(self) -> None:
        payload = {
            "organization_id": "org-1",
            "vehicle_id": self.vehicle_id,
            "device_id": "device-1",
            "trip_id": None,
            "lat": 2.0469,
            "lng": 45.3182,
            "speed_kph": 30,
            "heading_deg": 90,
            "alarm_flags": 0,
            "event_time": datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc).isoformat(),
            "is_backfill": False,
        }
        await self.redis.set(self._key, json.dumps(payload))

        port = RedisLatestPositionPort(
            self.redis, clock=self.clock, id_generator=self.id_generator
        )
        position = await port.get_latest(VehicleId(self.vehicle_id))

        self.assertIsNotNone(position)
        self.assertEqual(position.position.latitude, 2.0469)
        self.assertEqual(position.speed_kph.value, 30)

    async def test_no_key_returns_none(self) -> None:
        port = RedisLatestPositionPort(
            self.redis, clock=self.clock, id_generator=self.id_generator
        )
        position = await port.get_latest(VehicleId(self.vehicle_id))
        self.assertIsNone(position)


if __name__ == "__main__":
    unittest.main()
