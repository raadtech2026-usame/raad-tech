"""`LocationHandler` (`0x0200`) and `BulkLocationHandler` (`0x0704`) (Phase 9.6; JT808 Technical
Design §8/§10, JT/T 808-2013 §8.18/§8.49). Exercises both handlers directly against a real
`DeviceSessionManager` (in-memory, no-op close) and a recording `EventPublisher` fake, matching
the task's explicit verification list: single position report, batch position report, backfill
detection, duplicate timestamp handling, alarm flag mapping, speed mapping, heading mapping,
latitude/longitude precision, application service invocation (here: publisher invocation, per
the resolved event-driven architecture), malformed position packets, authenticated session
required.
"""

import unittest
from datetime import datetime, timezone

from src.dispatcher.handler import HandlerContext
from src.events.device_position_reported import DevicePositionReported
from src.handlers.bulk_location_handler import BulkLocationHandler
from src.handlers.location_handler import LocationHandler
from src.protocol.exceptions import MalformedFrameError
from src.protocol.message import InboundMessage
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from tests.test_position_body import _build_body

TERMINAL_ID = "013800138000"


def _make_message(
    message_id: int, *, body: bytes, terminal_id: str = TERMINAL_ID
) -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        terminal_id=terminal_id,
        serial_no=1,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DevicePositionReported] = []

    async def publish(self, event: DevicePositionReported) -> None:
        self.published.append(event)


class LocationHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def _authenticated_context(self, **kwargs) -> HandlerContext:
        async def noop_close(cid, reason):
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )
        await device_sessions.create(
            connection_id="conn-1",
            terminal_id=kwargs.pop("terminal_id", TERMINAL_ID),
            device_id=kwargs.pop("device_id", "device-1"),
            vehicle_id=kwargs.pop("vehicle_id", "vehicle-1"),
            organization_id=kwargs.pop("organization_id", "org-1"),
        )
        return HandlerContext(connection_id="conn-1", device_sessions=device_sessions)

    async def test_single_position_report_publishes_one_event(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        result = await handler.handle(
            _make_message(0x0200, body=_build_body()), context
        )

        self.assertEqual(len(publisher.published), 1)
        self.assertIsNone(result.response_message_id)  # no wire response, per design

    async def test_publisher_invocation_carries_resolved_identity(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context(
            device_id="dev-42", vehicle_id="veh-42", organization_id="org-42"
        )

        await handler.handle(_make_message(0x0200, body=_build_body()), context)

        event = publisher.published[0]
        self.assertEqual(event.device_id, "dev-42")
        self.assertEqual(event.vehicle_id, "veh-42")
        self.assertEqual(event.organization_id, "org-42")
        self.assertEqual(event.terminal_id, TERMINAL_ID)

    async def test_position_report_is_not_flagged_as_backfill(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        await handler.handle(_make_message(0x0200, body=_build_body()), context)

        self.assertFalse(publisher.published[0].is_backfill)

    async def test_trip_id_is_none_no_read_model_built_yet(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        await handler.handle(_make_message(0x0200, body=_build_body()), context)

        self.assertIsNone(publisher.published[0].trip_id)

    async def test_alarm_flags_map_through_verbatim(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        await handler.handle(
            _make_message(0x0200, body=_build_body(alarm_flags=0x00000021)), context
        )

        self.assertEqual(publisher.published[0].alarm_flags, 0x00000021)

    async def test_speed_maps_with_unit_conversion(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        await handler.handle(
            _make_message(0x0200, body=_build_body(raw_speed=456)),
            context,  # 45.6 -> 46
        )

        self.assertEqual(publisher.published[0].speed_kph, 46)

    async def test_heading_maps_verbatim(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        await handler.handle(
            _make_message(0x0200, body=_build_body(heading_deg=123)), context
        )

        self.assertEqual(publisher.published[0].heading_deg, 123)

    async def test_latitude_longitude_precision_preserved_through_mapping(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        await handler.handle(
            _make_message(
                0x0200,
                body=_build_body(
                    status=0b0000, raw_latitude=39_908_822, raw_longitude=116_397_470
                ),
            ),
            context,
        )

        event = publisher.published[0]
        self.assertAlmostEqual(event.latitude, 39.908822)
        self.assertAlmostEqual(event.longitude, 116.397470)

    async def test_malformed_position_body_raises_rather_than_publishes(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        with self.assertRaises(MalformedFrameError):
            await handler.handle(_make_message(0x0200, body=b"\x00" * 10), context)

        self.assertEqual(publisher.published, [])

    async def test_unauthenticated_terminal_drops_without_publishing_or_crashing(
        self,
    ) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)

        async def noop_close(cid, reason):
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )
        context = HandlerContext(
            connection_id="conn-1", device_sessions=device_sessions
        )

        result = await handler.handle(
            _make_message(0x0200, body=_build_body()), context
        )

        self.assertEqual(publisher.published, [])
        self.assertFalse(result.close_connection_after)  # dropped, connection untouched

    async def test_session_missing_vehicle_id_drops_without_publishing(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)

        async def noop_close(cid, reason):
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )
        await device_sessions.create(
            connection_id="conn-1",
            terminal_id=TERMINAL_ID,
            device_id="device-1",
            vehicle_id=None,  # incomplete identity
            organization_id="org-1",
        )
        context = HandlerContext(
            connection_id="conn-1", device_sessions=device_sessions
        )

        await handler.handle(_make_message(0x0200, body=_build_body()), context)

        self.assertEqual(publisher.published, [])

    async def test_duplicate_timestamp_positions_both_publish_unchanged(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        body = _build_body()
        await handler.handle(_make_message(0x0200, body=body), context)
        await handler.handle(_make_message(0x0200, body=body), context)

        self.assertEqual(len(publisher.published), 2)
        self.assertEqual(
            publisher.published[0].event_time, publisher.published[1].event_time
        )


class BulkLocationHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def _authenticated_context(self) -> HandlerContext:
        async def noop_close(cid, reason):
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )
        await device_sessions.create(
            connection_id="conn-1",
            terminal_id=TERMINAL_ID,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        return HandlerContext(connection_id="conn-1", device_sessions=device_sessions)

    def _bulk_body(
        self, item_bodies: list[bytes], *, position_data_type: int = 1
    ) -> bytes:
        body = len(item_bodies).to_bytes(2, "big") + bytes([position_data_type])
        for item_body in item_bodies:
            body += len(item_body).to_bytes(2, "big") + item_body
        return body

    async def test_batch_position_report_publishes_one_event_per_item(self) -> None:
        publisher = RecordingEventPublisher()
        handler = BulkLocationHandler(publisher)
        context = await self._authenticated_context()

        body = self._bulk_body([_build_body(), _build_body(), _build_body()])
        await handler.handle(_make_message(0x0704, body=body), context)

        self.assertEqual(len(publisher.published), 3)

    async def test_all_batch_items_are_flagged_as_backfill(self) -> None:
        publisher = RecordingEventPublisher()
        handler = BulkLocationHandler(publisher)
        context = await self._authenticated_context()

        body = self._bulk_body([_build_body(), _build_body()], position_data_type=0)
        await handler.handle(_make_message(0x0704, body=body), context)

        self.assertTrue(all(event.is_backfill for event in publisher.published))

    async def test_backfill_events_carry_original_device_reported_time(self) -> None:
        publisher = RecordingEventPublisher()
        handler = BulkLocationHandler(publisher)
        context = await self._authenticated_context()

        from tests.test_position_body import _encode_bcd_time

        old_time = _encode_bcd_time(2026, 1, 1, 0, 0, 0)
        item_body = _build_body(time_bytes=old_time)
        body = self._bulk_body([item_body])

        await handler.handle(_make_message(0x0704, body=body), context)

        event = publisher.published[0]
        self.assertEqual(
            event.event_time, datetime(2025, 12, 31, 16, 0, 0, tzinfo=timezone.utc)
        )
        # received_at is stamped "now", not the device's original event_time.
        self.assertNotEqual(event.received_at.date(), event.event_time.date())

    async def test_events_publish_in_wire_order(self) -> None:
        publisher = RecordingEventPublisher()
        handler = BulkLocationHandler(publisher)
        context = await self._authenticated_context()

        item_bodies = [
            _build_body(raw_latitude=n * 1_000_000, raw_longitude=n * 1_000_000)
            for n in (1, 2, 3)
        ]
        body = self._bulk_body(item_bodies)

        await handler.handle(_make_message(0x0704, body=body), context)

        latitudes = [round(event.latitude) for event in publisher.published]
        self.assertEqual(latitudes, [1, 2, 3])

    async def test_empty_batch_publishes_nothing(self) -> None:
        publisher = RecordingEventPublisher()
        handler = BulkLocationHandler(publisher)
        context = await self._authenticated_context()

        body = self._bulk_body([])
        await handler.handle(_make_message(0x0704, body=body), context)

        self.assertEqual(publisher.published, [])

    async def test_malformed_batch_raises_rather_than_publishes(self) -> None:
        publisher = RecordingEventPublisher()
        handler = BulkLocationHandler(publisher)
        context = await self._authenticated_context()

        with self.assertRaises(MalformedFrameError):
            await handler.handle(_make_message(0x0704, body=b"\x00"), context)

        self.assertEqual(publisher.published, [])

    async def test_unauthenticated_terminal_drops_batch_without_publishing(
        self,
    ) -> None:
        publisher = RecordingEventPublisher()
        handler = BulkLocationHandler(publisher)

        async def noop_close(cid, reason):
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )
        context = HandlerContext(
            connection_id="conn-1", device_sessions=device_sessions
        )

        body = self._bulk_body([_build_body()])
        result = await handler.handle(_make_message(0x0704, body=body), context)

        self.assertEqual(publisher.published, [])
        self.assertFalse(result.close_connection_after)


if __name__ == "__main__":
    unittest.main()
