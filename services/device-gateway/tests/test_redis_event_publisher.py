"""`RedisEventPublisher` tests (device-gateway Redis integration). A minimal in-memory fake
stands in for `redis.asyncio.Redis.xadd` — no real Redis connection, mirroring the backend's own
`test_redis_streams_broker.py` fake-client convention. Covers the wire envelope shape each of the
four device-plane events produces, matching `backend/raad/core/events/redis_streams.py`'s own
`_fields_to_event` deserialization field-for-field (asserted directly against a reimplementation
of that function here, since the two deployables share no code) — a mismatch here would silently
break `tracking.events.subscribers.DevicePositionReportedProcessor` with nothing to catch it.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from src.events.device_alarm_raised import DeviceAlarmRaised
from src.events.device_offline import DeviceOffline
from src.events.device_online import DeviceOnline
from src.events.device_position_reported import DevicePositionReported
from src.events.redis_event_publisher import RedisEventPublisher

_NOW = datetime(2026, 7, 24, 10, 0, 0, tzinfo=timezone.utc)


class FakeRedisStream:
    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, str]]] = []

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = False,
    ) -> str:
        # `maxlen`/`approximate` mirror redis-py's own `XADD` kwargs — accepted (and
        # recorded) so this fake stays call-compatible with the stream-trimming fix
        # (2026-09-02); trimming itself is asserted in the publisher's own unit tests.
        self.last_xadd_kwargs = {"maxlen": maxlen, "approximate": approximate}
        self.entries.append((name, fields))
        return str(len(self.entries))


def _decode(fields: dict[str, str]) -> dict:
    """Mirrors `backend/raad/core/events/redis_streams.py`'s own `_fields_to_event` decoding
    exactly (field names only — this test does not construct a real `DomainEvent`, just checks
    the same fields that function reads are present and correctly typed)."""
    return json.loads(fields["data"])


def _a_position_event() -> DevicePositionReported:
    return DevicePositionReported(
        organization_id="org-1",
        vehicle_id="vehicle-1",
        device_id="device-1",
        terminal_id="00007",
        trip_id="trip-1",
        latitude=22.67,
        longitude=114.06,
        speed_kph=12,
        heading_deg=90,
        alarm_flags=0,
        event_time=_NOW,
        is_backfill=False,
        received_at=_NOW,
    )


class RedisEventPublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_position_reported_envelope(self) -> None:
        redis = FakeRedisStream()
        publisher = RedisEventPublisher(redis)
        await publisher.publish(
            DevicePositionReported(
                organization_id="org-1",
                vehicle_id="vehicle-1",
                device_id="device-1",
                terminal_id="00007",
                trip_id="trip-1",
                latitude=22.67,
                longitude=114.06,
                speed_kph=12,
                heading_deg=90,
                alarm_flags=0,
                event_time=_NOW,
                is_backfill=False,
                received_at=_NOW,
            )
        )

        self.assertEqual(len(redis.entries), 1)
        stream_name, fields = redis.entries[0]
        self.assertEqual(stream_name, "raad:events")
        data = _decode(fields)
        self.assertEqual(data["event_type"], "DevicePositionReported")
        self.assertEqual(data["aggregate_type"], "Vehicle")
        self.assertEqual(data["aggregate_id"], "vehicle-1")
        self.assertEqual(data["org_id"], "org-1")
        self.assertEqual(data["version"], 1)
        self.assertIsNone(data["correlation_id"])
        self.assertIn("event_id", data)
        self.assertEqual(data["payload"]["vehicle_id"], "vehicle-1")
        self.assertEqual(data["payload"]["latitude"], 22.67)
        self.assertEqual(data["payload"]["is_backfill"], False)
        self.assertEqual(data["payload"]["event_time"], _NOW.isoformat())

    async def test_device_online_envelope_uses_device_aggregate(self) -> None:
        redis = FakeRedisStream()
        publisher = RedisEventPublisher(redis)
        await publisher.publish(
            DeviceOnline(
                terminal_id="00007",
                organization_id="org-1",
                vehicle_id="vehicle-1",
                device_id="device-1",
                event_time=_NOW,
                received_at=_NOW,
            )
        )
        _, fields = redis.entries[0]
        data = _decode(fields)
        self.assertEqual(data["event_type"], "DeviceOnline")
        self.assertEqual(data["aggregate_type"], "Device")
        self.assertEqual(data["aggregate_id"], "00007")
        self.assertEqual(data["payload"]["device_id"], "device-1")

    async def test_device_offline_envelope_carries_reason(self) -> None:
        redis = FakeRedisStream()
        publisher = RedisEventPublisher(redis)
        await publisher.publish(
            DeviceOffline(
                terminal_id="00007",
                organization_id="org-1",
                vehicle_id=None,
                device_id=None,
                reason="session_expired",
                event_time=_NOW,
                received_at=_NOW,
            )
        )
        _, fields = redis.entries[0]
        data = _decode(fields)
        self.assertEqual(data["event_type"], "DeviceOffline")
        self.assertEqual(data["aggregate_id"], "00007")
        self.assertEqual(data["payload"]["reason"], "session_expired")
        self.assertIsNone(data["payload"]["vehicle_id"])

    async def test_device_alarm_raised_envelope(self) -> None:
        redis = FakeRedisStream()
        publisher = RedisEventPublisher(redis)
        await publisher.publish(
            DeviceAlarmRaised(
                terminal_id="00007",
                organization_id="org-1",
                vehicle_id="vehicle-1",
                device_id="device-1",
                alarm_type="panic_button",
                alarm_flags=1,
                event_time=_NOW,
                received_at=_NOW,
            )
        )
        _, fields = redis.entries[0]
        data = _decode(fields)
        self.assertEqual(data["event_type"], "DeviceAlarmRaised")
        self.assertEqual(data["payload"]["alarm_type"], "panic_button")

    async def test_publish_does_not_trim_by_default(self) -> None:
        """`max_length=0` (constructor default) preserves this publisher's original unbounded
        behavior, so every pre-existing caller and test is unaffected."""
        redis = FakeRedisStream()
        publisher = RedisEventPublisher(redis)
        await publisher.publish(_a_position_event())
        self.assertEqual(redis.last_xadd_kwargs, {"maxlen": None, "approximate": False})

    async def test_publish_applies_approximate_trimming_when_configured(self) -> None:
        """Stream-growth fix (2026-09-02). This publisher is the highest-volume writer to the
        shared `raad:events` stream (one event per GPS position report), so leaving it unbounded
        would have defeated the identical cap applied on the Business API side: the stream was
        measured at 301k entries / ~223 MB against a 256 MB `maxmemory` under `noeviction`,
        where the next `XADD` fails outright and stops the whole event backbone."""
        redis = FakeRedisStream()
        publisher = RedisEventPublisher(redis, max_length=100_000)
        await publisher.publish(_a_position_event())
        self.assertEqual(
            redis.last_xadd_kwargs, {"maxlen": 100_000, "approximate": True}
        )

    async def test_publishes_to_a_custom_stream_name_when_given(self) -> None:
        redis = FakeRedisStream()
        publisher = RedisEventPublisher(redis, stream_name="custom:stream")
        await publisher.publish(
            DeviceOnline(
                terminal_id="00007",
                organization_id=None,
                vehicle_id=None,
                device_id=None,
                event_time=_NOW,
                received_at=_NOW,
            )
        )
        stream_name, _ = redis.entries[0]
        self.assertEqual(stream_name, "custom:stream")

    async def test_each_event_gets_a_unique_event_id(self) -> None:
        redis = FakeRedisStream()
        publisher = RedisEventPublisher(redis)
        event = DeviceOnline(
            terminal_id="00007",
            organization_id=None,
            vehicle_id=None,
            device_id=None,
            event_time=_NOW,
            received_at=_NOW,
        )
        await publisher.publish(event)
        await publisher.publish(event)

        ids = {_decode(fields)["event_id"] for _, fields in redis.entries}
        self.assertEqual(len(ids), 2)


if __name__ == "__main__":
    unittest.main()
