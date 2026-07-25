"""`RedisLatestPositionWriter`/`to_snapshot_payload` tests (`docs/architecture/
post-f7-production-readiness-roadmap.md` Phase A item A2). A minimal in-memory fake stands in for
`redis.asyncio.Redis.set`, mirroring `test_redis_event_publisher.py`'s own fake-client convention.
Asserts the exact wire-payload shape `backend/raad/modules/tracking/infra/adapters.
RedisLatestPositionPort.get_latest` parses (field names only — this test does not import backend
code, the two deployables share none; see `redis_latest_position_writer.py`'s own module
docstring for why this shape is a strict, tested contract rather than re-derived from memory).
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from src.events.device_position_reported import DevicePositionReported
from src.latest_position.redis_latest_position_writer import (
    RedisLatestPositionWriter,
    to_snapshot_payload,
)
from src.latest_position.writer_port import LoggingLatestPositionWriter

_NOW = datetime(2026, 7, 24, 10, 0, 0, tzinfo=timezone.utc)


def _make_event(*, is_backfill: bool = False, trip_id: str | None = None) -> DevicePositionReported:
    return DevicePositionReported(
        organization_id="org-1",
        vehicle_id="vehicle-1",
        device_id="device-1",
        terminal_id="00007",
        trip_id=trip_id,
        latitude=22.672803,
        longitude=114.059395,
        speed_kph=12,
        heading_deg=90,
        alarm_flags=0,
        event_time=_NOW,
        is_backfill=is_backfill,
        received_at=_NOW,
    )


class FakeRedisKeyValue:
    def __init__(self) -> None:
        self.sets: list[tuple[str, str]] = []

    async def set(self, key: str, value: str) -> None:
        self.sets.append((key, value))


class ToSnapshotPayloadTests(unittest.TestCase):
    def test_uses_abbreviated_lat_lng_keys_matching_the_backend_parser(self) -> None:
        payload = to_snapshot_payload(_make_event())
        self.assertEqual(payload["lat"], 22.672803)
        self.assertEqual(payload["lng"], 114.059395)
        self.assertNotIn("latitude", payload)
        self.assertNotIn("longitude", payload)

    def test_carries_every_field_the_backend_adapter_reads(self) -> None:
        payload = to_snapshot_payload(_make_event(trip_id="trip-1"))
        self.assertEqual(
            set(payload.keys()),
            {
                "organization_id",
                "vehicle_id",
                "device_id",
                "trip_id",
                "lat",
                "lng",
                "speed_kph",
                "heading_deg",
                "alarm_flags",
                "event_time",
                "is_backfill",
            },
        )
        self.assertEqual(payload["organization_id"], "org-1")
        self.assertEqual(payload["vehicle_id"], "vehicle-1")
        self.assertEqual(payload["device_id"], "device-1")
        self.assertEqual(payload["trip_id"], "trip-1")
        self.assertEqual(payload["speed_kph"], 12)
        self.assertEqual(payload["heading_deg"], 90)
        self.assertEqual(payload["alarm_flags"], 0)
        self.assertEqual(payload["event_time"], _NOW.isoformat())
        self.assertFalse(payload["is_backfill"])

    def test_null_trip_id_stays_null_not_omitted(self) -> None:
        payload = to_snapshot_payload(_make_event(trip_id=None))
        self.assertIn("trip_id", payload)
        self.assertIsNone(payload["trip_id"])


class RedisLatestPositionWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_to_the_vehicle_id_last_key(self) -> None:
        redis = FakeRedisKeyValue()
        writer = RedisLatestPositionWriter(redis)

        await writer.write(_make_event())

        self.assertEqual(len(redis.sets), 1)
        key, raw_value = redis.sets[0]
        self.assertEqual(key, "vehicle:vehicle-1:last")
        self.assertEqual(json.loads(raw_value), to_snapshot_payload(_make_event()))

    async def test_backfilled_positions_never_overwrite_the_live_snapshot(self) -> None:
        """`.claude/rules/jt808.md` #3 / Phase 2 §22.2: a late/buffered position must never
        overwrite a fresher live reading already sitting in Redis."""
        redis = FakeRedisKeyValue()
        writer = RedisLatestPositionWriter(redis)

        await writer.write(_make_event(is_backfill=True))

        self.assertEqual(redis.sets, [])


class LoggingLatestPositionWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_never_raises_without_redis_configured(self) -> None:
        writer = LoggingLatestPositionWriter()
        await writer.write(_make_event())  # must not raise


if __name__ == "__main__":
    unittest.main()
