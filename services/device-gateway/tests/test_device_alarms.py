"""ADR-0055/0057 — the JT/T 808 alarm taxonomy, rising-edge `DeviceAlarmRaised` from
`LocationHandler`, its publisher wiring, the alarm-state stores and the `0x8203` builder.

Synthetic frames only: the procured terminal is offline, so which bits it really sets is not
verified here."""

import json
import struct
import unittest
from datetime import datetime, timezone

from src.alarms.alarm_state import InMemoryAlarmStateStore, RedisAlarmStateStore
from src.events.device_alarm_raised import DeviceAlarmRaised
from src.events.device_position_reported import DevicePositionReported
from src.events.redis_event_publisher import _fields_for
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.vendors.jt808.alarm_taxonomy import raised_alarm_types
from src.vendors.jt808.commands.redis_video_signaling_consumer import _BUILDERS
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.dispatcher.handler import HandlerContext
from src.vendors.jt808.handlers.location_handler import LocationHandler
from src.vendors.jt808.protocol.message import InboundMessage

#: The real 2026-09-19 capture from test_video_signal_status.py; its alarm word is 0x00000020
#: (antenna disconnected), a bit RAAD does not interpret.
REAL_BODY = bytes.fromhex(
    "00000020000c0001001ed86e02b2f255000000000000260919170833"
    "010400000000040200000302000014040000000515040000000a1604000000001702000d"
    "18030000001904000000002504000000002a02000030011f310100520100ad020081"
)
TERMINAL_ID = "00000000014482607571"
SOS, OVERSPEED, COLLISION = 1 << 0, 1 << 1, 1 << 29


def _body(alarm_word: int) -> bytes:
    return struct.pack(">I", alarm_word) + REAL_BODY[4:]


def _message(body: bytes) -> InboundMessage:
    return InboundMessage(
        message_id=0x0200,
        terminal_id=TERMINAL_ID,
        serial_no=1,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


class TaxonomyTests(unittest.TestCase):
    def test_only_newly_set_recognised_bits_are_raised(self) -> None:
        self.assertEqual(raised_alarm_types(None, SOS | 0x20), ["sos"])
        self.assertEqual(raised_alarm_types(SOS, SOS), [])
        self.assertEqual(raised_alarm_types(SOS, SOS | COLLISION | OVERSPEED), ["overspeed", "collision"])
        self.assertEqual(raised_alarm_types(SOS, 0), [])
        self.assertEqual(raised_alarm_types(0, 1 << 5), [])  # unmapped bit


class _Publisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event) -> None:
        self.published.append(event)


class _FailingState:
    async def swap(self, terminal_id, alarm_flags):
        raise RuntimeError("redis down")


class LocationHandlerAlarmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        async def noop_close(cid, reason):
            return None

        self.sessions = DeviceSessionManager(registry=DeviceSessionRegistry(), close_connection=noop_close)
        await self.sessions.create(
            connection_id="conn-1",
            terminal_id=TERMINAL_ID,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        self.context = HandlerContext(connection_id="conn-1", device_sessions=self.sessions)
        self.publisher = _Publisher()
        self.state = InMemoryAlarmStateStore()
        self.handler = LocationHandler(self.publisher, alarm_state=self.state)

    def alarms(self) -> list[DeviceAlarmRaised]:
        return [e for e in self.publisher.published if isinstance(e, DeviceAlarmRaised)]

    async def test_sos_is_raised_once_while_the_bit_stays_set(self) -> None:
        await self.handler.handle(_message(_body(0)), self.context)
        await self.handler.handle(_message(_body(SOS)), self.context)
        await self.handler.handle(_message(_body(SOS)), self.context)
        [alarm] = self.alarms()
        self.assertEqual((alarm.alarm_type, alarm.vehicle_id, alarm.organization_id), ("sos", "vehicle-1", "org-1"))
        self.assertEqual(alarm.alarm_flags, SOS)
        self.assertIsNotNone(alarm.speed_kph)

    async def test_it_is_raised_again_after_it_clears(self) -> None:
        for word in (SOS, 0, SOS):
            await self.handler.handle(_message(_body(word)), self.context)
        self.assertEqual([a.alarm_type for a in self.alarms()], ["sos", "sos"])

    async def test_the_real_capture_raises_nothing(self) -> None:
        await self.handler.handle(_message(REAL_BODY), self.context)
        self.assertEqual(self.alarms(), [])

    async def test_a_state_failure_never_costs_the_position_or_its_ack(self) -> None:
        handler = LocationHandler(self.publisher, alarm_state=_FailingState())
        result = await handler.handle(_message(_body(SOS)), self.context)
        self.assertEqual(len([e for e in self.publisher.published if isinstance(e, DevicePositionReported)]), 1)
        self.assertEqual(self.alarms(), [])
        self.assertIsNotNone(result.response_body)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.calls: list[tuple] = []

    async def set(self, key, value, ex=None, get=False):
        self.calls.append((key, ex, get))
        previous = self.values.get(key)
        self.values[key] = value.encode()
        return previous


class AlarmStateStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_redis_store_returns_the_previous_word_and_expires(self) -> None:
        redis = _FakeRedis()
        store = RedisAlarmStateStore(redis)  # type: ignore[arg-type]
        self.assertIsNone(await store.swap("T1", SOS))
        self.assertEqual(await store.swap("T1", 0), SOS)
        key, ttl, get = redis.calls[0]
        self.assertEqual(key, "device-gateway:alarm-flags:T1")
        self.assertTrue(get)
        self.assertGreater(ttl, 0)


class PublisherAndCommandTests(unittest.TestCase):
    def test_the_redis_envelope_carries_type_position_and_time(self) -> None:
        now = datetime(2026, 9, 30, 7, 0, tzinfo=timezone.utc)
        event = DeviceAlarmRaised(
            terminal_id=TERMINAL_ID,
            organization_id="org-1",
            vehicle_id="vehicle-1",
            device_id="device-1",
            alarm_type="collision",
            alarm_flags=COLLISION,
            event_time=now,
            received_at=now,
            latitude=2.04,
            longitude=45.3,
            speed_kph=41.0,
        )
        data = json.loads(_fields_for(event)["data"])
        self.assertEqual(data["event_type"], "DeviceAlarmRaised")
        payload = data["payload"]
        self.assertEqual((payload["alarm_type"], payload["speed_kph"], payload["latitude"]), ("collision", 41.0, 2.04))
        self.assertEqual(payload["event_time"], now.isoformat())

    def test_confirm_alarm_encodes_0x8203(self) -> None:
        message_id, body = _BUILDERS["confirm_alarm"]({"alarm_serial_no": 0, "alarm_type_mask": 1})
        self.assertEqual(message_id, message_ids.CONFIRM_ALARM)
        self.assertEqual(message_id, 0x8203)
        self.assertEqual(body, b"\x00\x00\x00\x00\x00\x01")
        with self.assertRaises(ValueError):
            _BUILDERS["confirm_alarm"]({"alarm_serial_no": -1, "alarm_type_mask": 1})


if __name__ == "__main__":
    unittest.main()
