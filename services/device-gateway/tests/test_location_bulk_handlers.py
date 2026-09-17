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

from src.vendors.jt808.dispatcher.handler import HandlerContext
from src.events.device_position_reported import DevicePositionReported
from src.session.device_session import DeviceConnectivityState
from src.vendors.jt808.handlers.bulk_location_handler import BulkLocationHandler
from src.vendors.jt808.handlers.location_handler import LocationHandler
from src.vendors.jt808.protocol.message import InboundMessage
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from tests.test_position_body import _build_body

TERMINAL_ID = "013800138000"


def _make_message(
    message_id: int, *, body: bytes, terminal_id: str = TERMINAL_ID, serial_no: int = 1
) -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        terminal_id=terminal_id,
        serial_no=serial_no,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


def _decode_general_response(result) -> tuple[int, int, int]:
    """(original serial, original message id, result code) from a `0x8001` handler result —
    Table 5.21's WORD/WORD/BYTE layout."""
    body = result.response_body
    return (
        int.from_bytes(body[0:2], "big"),
        int.from_bytes(body[2:4], "big"),
        body[4],
    )


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DevicePositionReported] = []

    async def publish(self, event: DevicePositionReported) -> None:
        self.published.append(event)


class FailingEventPublisher:
    """Stands in for a broker write failure (e.g. Redis unreachable or out of memory)."""

    def __init__(self, *, fail_on_call: int = 1) -> None:
        self.published: list[DevicePositionReported] = []
        self._fail_on_call = fail_on_call

    async def publish(self, event: DevicePositionReported) -> None:
        if len(self.published) + 1 == self._fail_on_call:
            raise ConnectionError("broker unavailable")
        self.published.append(event)


class RecordingLatestPositionWriter:
    def __init__(self) -> None:
        self.written: list[DevicePositionReported] = []

    async def write(self, event: DevicePositionReported) -> None:
        self.written.append(event)


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
        # Supplier spec §7.8.1: 0x0200 is not a no-reply message, so it is acknowledged.
        self.assertEqual(result.response_message_id, 0x8001)
        self.assertEqual(_decode_general_response(result), (1, 0x0200, 0))
        self.assertFalse(result.close_connection_after)

    async def test_acknowledgement_echoes_the_reports_own_serial_number(self) -> None:
        """The terminal matches a reply to its message by serial number and message ID (spec
        §7.8.1: a mismatched reply must not end its wait), so both must be echoed verbatim."""
        handler = LocationHandler(RecordingEventPublisher())
        context = await self._authenticated_context()

        for serial_no in (0, 0x1234, 0xFFFF):
            result = await handler.handle(
                _make_message(0x0200, body=_build_body(), serial_no=serial_no), context
            )
            self.assertEqual(_decode_general_response(result), (serial_no, 0x0200, 0))

    async def test_publish_failure_sends_no_acknowledgement(self) -> None:
        """A report RAAD failed to publish must stay unacknowledged, so the terminal retransmits
        it rather than discarding a point that was never recorded."""
        handler = LocationHandler(FailingEventPublisher())
        context = await self._authenticated_context()

        with self.assertRaises(ConnectionError):
            await handler.handle(_make_message(0x0200, body=_build_body()), context)

    async def test_fix_invalid_report_is_still_acknowledged_and_flagged(self) -> None:
        """Acknowledging is about receipt, not GPS quality: the GPS-validity rule is unchanged
        (the event still carries `is_gps_valid=False`), and the report is still answered."""
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        result = await handler.handle(
            _make_message(0x0200, body=_build_body(status=0b0000)), context
        )

        self.assertFalse(publisher.published[0].is_gps_valid)
        self.assertEqual(_decode_general_response(result), (1, 0x0200, 0))

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

    async def test_accepted_position_report_promotes_session_online(self) -> None:
        """JT808 device-plane integration gap: `LocationHandler` now calls `touch()` on every
        accepted position, mirroring `MdvrPositionHandler`'s identical, already-established
        precedent — a terminal reporting GPS but never sending a heartbeat must still be
        promoted `AUTHENTICATED -> ONLINE`, not left to expire under the idle-timeout sweep
        while actively transmitting."""
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()
        session = await context.device_sessions.resolve(TERMINAL_ID)
        self.assertEqual(session.state, DeviceConnectivityState.AUTHENTICATED)

        await handler.handle(_make_message(0x0200, body=_build_body()), context)

        self.assertEqual(session.state, DeviceConnectivityState.ONLINE)

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

    async def test_malformed_position_body_is_answered_with_message_error_not_published(
        self,
    ) -> None:
        """Result `2` (message error, Table 5.21) stops the terminal retransmitting a body that
        can never be parsed; nothing is published."""
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        result = await handler.handle(
            _make_message(0x0200, body=b"\x00" * 10, serial_no=7), context
        )

        self.assertEqual(publisher.published, [])
        self.assertEqual(_decode_general_response(result), (7, 0x0200, 2))
        self.assertFalse(result.close_connection_after)

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
        self.assertEqual(_decode_general_response(result), (1, 0x0200, 1))  # failure

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

    async def test_positioned_status_bit_yields_gps_valid_true(self) -> None:
        """Root-cause fix — RAAD Live Tracking wrong-location investigation."""
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        await handler.handle(
            _make_message(0x0200, body=_build_body(status=0b0010)), context
        )

        self.assertTrue(publisher.published[0].is_gps_valid)

    async def test_not_positioned_status_bit_yields_gps_valid_false(self) -> None:
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        await handler.handle(
            _make_message(0x0200, body=_build_body(status=0b0000)), context
        )

        self.assertFalse(publisher.published[0].is_gps_valid)

    async def test_positioned_but_implausible_coordinate_yields_gps_valid_false(
        self,
    ) -> None:
        """The wire's own "positioned" bit alone is not sufficient — an implausible
        coordinate (here, null island) must still be flagged invalid."""
        publisher = RecordingEventPublisher()
        handler = LocationHandler(publisher)
        context = await self._authenticated_context()

        await handler.handle(
            _make_message(
                0x0200,
                body=_build_body(status=0b0010, raw_latitude=0, raw_longitude=0),
            ),
            context,
        )

        self.assertFalse(publisher.published[0].is_gps_valid)

    async def test_writes_to_latest_position_writer_when_gps_valid(self) -> None:
        """Root-cause fix: `LocationHandler` previously took no `latest_position_writer` at
        all, so the live, primary JT/T 808 adapter never updated `vehicle:{id}:last`."""
        publisher = RecordingEventPublisher()
        writer = RecordingLatestPositionWriter()
        handler = LocationHandler(publisher, latest_position_writer=writer)
        context = await self._authenticated_context()

        await handler.handle(
            _make_message(0x0200, body=_build_body(status=0b0010)), context
        )

        self.assertEqual(len(writer.written), 1)
        self.assertTrue(writer.written[0].is_gps_valid)

    async def test_does_not_gate_publishing_when_gps_invalid(self) -> None:
        """A fix-invalid report is still published/persisted for audit — only the "latest
        known live position" cache must skip it (enforced inside the writer itself)."""
        publisher = RecordingEventPublisher()
        writer = RecordingLatestPositionWriter()
        handler = LocationHandler(publisher, latest_position_writer=writer)
        context = await self._authenticated_context()

        await handler.handle(
            _make_message(0x0200, body=_build_body(status=0b0000)), context
        )

        self.assertEqual(len(publisher.published), 1)
        self.assertFalse(publisher.published[0].is_gps_valid)
        # The writer is still called — gating is that port's own responsibility (tested in
        # test_latest_position_writer.py), not this handler's.
        self.assertEqual(len(writer.written), 1)


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
        result = await handler.handle(
            _make_message(0x0704, body=body, serial_no=0x0A0B), context
        )

        self.assertEqual(len(publisher.published), 3)
        # One acknowledgement for the whole batch, echoing its serial and message ID.
        self.assertEqual(result.response_message_id, 0x8001)
        self.assertEqual(_decode_general_response(result), (0x0A0B, 0x0704, 0))

    async def test_publish_failure_part_way_through_a_batch_sends_no_acknowledgement(
        self,
    ) -> None:
        publisher = FailingEventPublisher(fail_on_call=2)
        handler = BulkLocationHandler(publisher)
        context = await self._authenticated_context()

        body = self._bulk_body([_build_body(), _build_body(), _build_body()])
        with self.assertRaises(ConnectionError):
            await handler.handle(_make_message(0x0704, body=body), context)

        self.assertEqual(len(publisher.published), 1)

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

    async def test_malformed_batch_is_answered_with_message_error_not_published(self) -> None:
        publisher = RecordingEventPublisher()
        handler = BulkLocationHandler(publisher)
        context = await self._authenticated_context()

        result = await handler.handle(
            _make_message(0x0704, body=b"\x00", serial_no=9), context
        )

        self.assertEqual(publisher.published, [])
        self.assertEqual(_decode_general_response(result), (9, 0x0704, 2))

    async def test_batch_items_carry_gps_valid_per_item(self) -> None:
        """Root-cause fix — RAAD Live Tracking wrong-location investigation: each batch item's
        own "positioned" status bit is evaluated independently, not once for the whole message."""
        publisher = RecordingEventPublisher()
        handler = BulkLocationHandler(publisher)
        context = await self._authenticated_context()

        body = self._bulk_body(
            [_build_body(status=0b0010), _build_body(status=0b0000)]
        )
        await handler.handle(_make_message(0x0704, body=body), context)

        self.assertTrue(publisher.published[0].is_gps_valid)
        self.assertFalse(publisher.published[1].is_gps_valid)

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
        self.assertEqual(_decode_general_response(result), (1, 0x0704, 1))  # failure


if __name__ == "__main__":
    unittest.main()
