"""`MdvrPositionHandler` (`V114`) tests — mirrors `test_location_bulk_handlers.py`'s conventions:
a real `DeviceSessionManager` (in-memory, no-op close) and a recording `EventPublisher` fake,
using the same real device-00007 worked example `test_mdvr_parser.py`/`test_mdvr_location_status.
py` already validate.
"""

import time
import unittest
from datetime import datetime, timezone

from src.events.device_position_reported import DevicePositionReported
from src.session.device_session import DeviceConnectivityState
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.vendors.lsz.dispatcher.handler import MdvrHandlerContext
from src.vendors.lsz.handlers.position_handler import MdvrPositionHandler
from src.vendors.lsz.protocol.message import MdvrInboundMessage

_LOCATION_STATUS_FIELDS = [
    "A0010",
    "114",
    "3",
    "338214000",
    "22",
    "40",
    "220920000",
    "0.00",
    "1521000",
    "000E00010101D383",
    "0000000000000000",
    "0.00",
    "0.00",
    "0.00",
    "0",
    "0.00",
    "2266",
    "0|0.00|0|0|0|0|0|0|0",
]


def _make_message(
    *, device_serial_number: str = "00007", drive_flag: str = "1"
) -> MdvrInboundMessage:
    return MdvrInboundMessage(
        keyword="V114",
        serial_no=192,
        device_serial_number=device_serial_number,
        workstation_serial_number=None,
        sent_at_raw="180903 135949",
        fields=_LOCATION_STATUS_FIELDS + [drive_flag],
        declared_length=165,
        received_at=datetime.now(timezone.utc),
    )


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DevicePositionReported] = []

    async def publish(self, event: DevicePositionReported) -> None:
        self.published.append(event)


class MdvrPositionHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def _authenticated_context(self) -> MdvrHandlerContext:
        async def noop_close(connection_id: str, reason: str) -> None:
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )
        await device_sessions.create(
            connection_id="conn-1",
            terminal_id="00007",
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        return MdvrHandlerContext(connection_id="conn-1", device_sessions=device_sessions)

    async def test_publishes_a_normalized_position_event(self) -> None:
        publisher = RecordingEventPublisher()
        handler = MdvrPositionHandler(publisher)
        context = await self._authenticated_context()

        result = await handler.handle(_make_message(), context)

        self.assertIsNone(result.response_keyword)
        self.assertEqual(len(publisher.published), 1)
        event = publisher.published[0]
        self.assertEqual(event.organization_id, "org-1")
        self.assertEqual(event.vehicle_id, "vehicle-1")
        self.assertEqual(event.device_id, "device-1")
        self.assertEqual(event.terminal_id, "00007")
        self.assertIsNone(event.trip_id)
        self.assertAlmostEqual(event.latitude, 22.672803, places=5)
        self.assertAlmostEqual(event.longitude, 114.059395, places=5)
        self.assertFalse(event.is_backfill)
        self.assertEqual(
            event.event_time, datetime(2018, 9, 3, 13, 59, 49, tzinfo=timezone.utc)
        )
        # Regression test for the ADR-0012 live-verification bug: this exact worked example's
        # raw "ground course" (1521000) and raw 64-bit alarm bitfield (0x000E00010101D383) both
        # fall outside the Business API tracking domain's HeadingDegrees ([0,360)) / AlarmFlags
        # (32-bit) ranges. Previously these flowed through unclamped and the domain's own
        # DomainError silently failed every position event from this vendor, forever. Both must
        # come through as the documented "uncertain -> 0" default, not the raw out-of-range value.
        self.assertEqual(event.heading_deg, 0)
        self.assertEqual(event.alarm_flags, 0)

    async def test_position_report_from_unauthenticated_device_is_dropped_not_crashed(
        self,
    ) -> None:
        publisher = RecordingEventPublisher()
        handler = MdvrPositionHandler(publisher)

        async def noop_close(connection_id: str, reason: str) -> None:
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )
        context = MdvrHandlerContext(connection_id="conn-1", device_sessions=device_sessions)

        result = await handler.handle(
            _make_message(device_serial_number="never-registered"), context
        )

        self.assertIsNone(result.response_keyword)
        self.assertEqual(publisher.published, [])

    async def test_no_wire_response_is_ever_sent(self) -> None:
        publisher = RecordingEventPublisher()
        handler = MdvrPositionHandler(publisher)
        context = await self._authenticated_context()

        result = await handler.handle(_make_message(), context)

        self.assertIsNone(result.response_keyword)
        self.assertFalse(result.close_connection_after)

    async def test_position_report_promotes_authenticated_session_to_online(self) -> None:
        """Regression test for the heartbeat/position `touch()` asymmetry
        (`docs/architecture/post-f7-production-readiness-roadmap.md` A1): previously only
        `MdvrHeartbeatHandler` called `touch()`, so a device sending only `V114` position
        reports (no `V109` heartbeats) was never promoted out of `AUTHENTICATED`."""
        publisher = RecordingEventPublisher()
        handler = MdvrPositionHandler(publisher)
        context = await self._authenticated_context()
        session = context.device_sessions.resolve("00007")
        assert session is not None
        self.assertEqual(session.state, DeviceConnectivityState.AUTHENTICATED)

        await handler.handle(_make_message(), context)

        self.assertEqual(session.state, DeviceConnectivityState.ONLINE)

    async def test_position_only_device_survives_a_sweep_cycle(self) -> None:
        """A device sending only position reports (no heartbeats) must not be swept
        `session_expired` while actively transmitting — the exact bug this handler's `touch()`
        call fixes. Simulates a session that would already be past the sweep's timeout, then
        proves a single position report is enough to keep it alive across `_sweep_once`."""
        publisher = RecordingEventPublisher()
        handler = MdvrPositionHandler(publisher)
        context = await self._authenticated_context()
        session = context.device_sessions.resolve("00007")
        assert session is not None
        session.last_seen_at = time.monotonic() - 1000  # already "expired" absent a fresh touch

        await handler.handle(_make_message(), context)
        await context.device_sessions._sweep_once(timeout_seconds=5.0)

        self.assertIsNotNone(context.device_sessions.resolve("00007"))
        self.assertEqual(session.state, DeviceConnectivityState.ONLINE)


if __name__ == "__main__":
    unittest.main()
