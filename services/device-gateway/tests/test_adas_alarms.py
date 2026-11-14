"""Unit tests for Su-biao T/JSATL12 Active Safety ADAS alarms (Item 0x64)."""

import struct
import unittest
from datetime import datetime, timezone

from src.events.device_alarm_raised import DeviceAlarmRaised
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.vendors.jt808.dispatcher.handler import HandlerContext
from src.vendors.jt808.handlers.location_handler import LocationHandler
from src.vendors.jt808.handlers.position_additional_info import (
    ITEM_ADAS_ALARM,
    adas_alarm_info,
    parse_additional_items,
)
from src.vendors.jt808.protocol.message import InboundMessage

TERMINAL_ID = "00000000014482607571"

# Real verified 28-byte basic position block from terminal 00000000014482607571:
# Alarm: 0x00000020, Status: 0x000c0001, Lat: 2021486 (0x001ed86e), Lon: 45281877 (0x02b2f255),
# Alt: 0, Speed: 0, Direction: 0, Time: 26-09-19 17:08:33
BASIC_BLOCK = bytes.fromhex("00000020000c0001001ed86e02b2f255000000000000260919170833")


def _build_0x64_payload(
    *,
    alarm_id: int = 1001,
    flag_status: int = 0,  # 0: start, 1: repeat, 2: end
    alarm_type: int = 1,   # 1: forward_collision
    alarm_level: int = 2,  # 2: critical
    front_speed: int = 35,
    front_distance_dm: int = 50,  # 5.0 meters
    deviation_type: int = 0,
    speed: int = 40,
    altitude: int = 15,
    lat_deg: float = 2.021486,
    lon_deg: float = 45.281877,
    bcd_time: bytes = bytes.fromhex("261114183000"),
    vehicle_state: int = 0,
) -> bytes:
    lat_int = int(lat_deg * 1_000_000)
    lon_int = int(lon_deg * 1_000_000)
    return (
        struct.pack(">IBBBBBB", alarm_id, flag_status, alarm_type, alarm_level, front_speed, front_distance_dm, deviation_type)
        + bytes([0, 0, speed])  # road_sign_type, road_sign_data, vehicle_speed
        + struct.pack(">HII", altitude, lat_int, lon_int)
        + bcd_time
        + struct.pack(">H", vehicle_state)
    )


class AdasParsingTests(unittest.TestCase):
    def test_missing_0x64_returns_none(self) -> None:
        self.assertIsNone(adas_alarm_info({}))

    def test_short_0x64_returns_none(self) -> None:
        self.assertIsNone(adas_alarm_info({ITEM_ADAS_ALARM: b"\x00" * 20}))

    def test_valid_forward_collision_payload(self) -> None:
        payload = _build_0x64_payload(alarm_type=1, front_distance_dm=52, speed=45)
        items = {ITEM_ADAS_ALARM: payload}
        info = adas_alarm_info(items)
        self.assertIsNotNone(info)
        self.assertEqual(info.alarm_type, "forward_collision")
        self.assertEqual(info.alarm_id, 1001)
        self.assertEqual(info.flag_status, 0)
        self.assertEqual(info.alarm_level, 2)
        self.assertEqual(info.front_vehicle_distance, 5.2)
        self.assertEqual(info.vehicle_speed, 45)
        self.assertAlmostEqual(info.latitude, 2.021486, places=6)
        self.assertAlmostEqual(info.longitude, 45.281877, places=6)
        self.assertIsNotNone(info.event_time)

    def test_lane_departure_payload(self) -> None:
        payload = _build_0x64_payload(alarm_type=2, deviation_type=1)  # 1 = left
        items = {ITEM_ADAS_ALARM: payload}
        info = adas_alarm_info(items)
        self.assertIsNotNone(info)
        self.assertEqual(info.alarm_type, "lane_departure")
        self.assertEqual(info.deviation_type, 1)

    def test_pedestrian_collision_payload(self) -> None:
        payload = _build_0x64_payload(alarm_type=4)
        items = {ITEM_ADAS_ALARM: payload}
        info = adas_alarm_info(items)
        self.assertIsNotNone(info)
        self.assertEqual(info.alarm_type, "pedestrian_collision")


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event) -> None:
        self.published.append(event)


def _message(body: bytes) -> InboundMessage:
    return InboundMessage(
        message_id=0x0200,
        terminal_id=TERMINAL_ID,
        serial_no=1,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


class LocationHandlerAdasTests(unittest.IsolatedAsyncioTestCase):
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
        self.publisher = RecordingPublisher()
        self.handler = LocationHandler(self.publisher)

    def _alarm_events(self) -> list[DeviceAlarmRaised]:
        return [e for e in self.publisher.published if isinstance(e, DeviceAlarmRaised)]

    async def test_adas_forward_collision_publishes_device_alarm_raised(self) -> None:
        payload_0x64 = _build_0x64_payload(alarm_type=1, speed=42)
        body = BASIC_BLOCK + bytes([ITEM_ADAS_ALARM, len(payload_0x64)]) + payload_0x64

        await self.handler.handle(_message(body), self.context)

        alarms = self._alarm_events()
        self.assertEqual(len(alarms), 1)
        alarm = alarms[0]
        self.assertEqual(alarm.alarm_type, "forward_collision")
        self.assertEqual(alarm.vehicle_id, "vehicle-1")
        self.assertEqual(alarm.organization_id, "org-1")
        self.assertEqual(alarm.speed_kph, 42)

    async def test_adas_end_of_alarm_publishes_no_alarm_event(self) -> None:
        # flag_status = 2 means end of alarm
        payload_0x64 = _build_0x64_payload(alarm_type=1, flag_status=2)
        body = BASIC_BLOCK + bytes([ITEM_ADAS_ALARM, len(payload_0x64)]) + payload_0x64

        await self.handler.handle(_message(body), self.context)
        self.assertEqual(self._alarm_events(), [])
