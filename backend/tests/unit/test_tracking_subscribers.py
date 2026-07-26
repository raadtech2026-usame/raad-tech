"""Unit tests for `modules.tracking.events.subscribers` (roadmap track B2, ADR-0009; Phase A
item A4 for the active-trip-resolution coverage below). Stdlib `unittest` — no `pytest`. Mirrors
`test_notification_subscribers.py`'s convention: fakes bound directly into a real
`core.di.container.Container`, keyed by the real types `DevicePositionReportedProcessor` resolves.

Covers: a live position event persists via `record_vehicle_position`; a backfill-flagged event
persists via `record_backfill_position` instead; optional fields (`speed_kph`/`heading_deg`/
`alarm_flags`) pass through as `None` when absent from the payload, matching
`RecordVehiclePositionCommand`'s own optional fields; `event.org_id` is used over a payload
duplicate when both are present; a live position's `trip_id` is resolved fresh via
`TripApplicationService.get_active_trip_for_vehicle` (never trusted from the payload), while a
backfilled position's `trip_id` passes through the payload unresolved.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.modules.tracking.application.commands import (
    RecordBackfillPositionCommand,
    RecordVehiclePositionCommand,
)
from raad.modules.tracking.application.ports import TrackingUnitOfWork
from raad.modules.tracking.application.services import TrackingApplicationService
from raad.modules.tracking.events.subscribers import DevicePositionReportedProcessor
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import GetActiveTripForVehicleQuery
from raad.modules.transport_ops.application.services import TripApplicationService

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


class _FakeUnitOfWork:
    """`Container.resolve` is a plain type-keyed lookup with no `isinstance` enforcement (see
    `test_notification_subscribers.py`'s identical `FakeTransportOpsUnitOfWork` precedent) - the
    fake `TrackingApplicationService` below never actually uses `uow`, so this needs no `async
    with` shape either, unlike that precedent's own fake."""


class _RecordingTrackingService:
    def __init__(self) -> None:
        self.recorded_positions: list[RecordVehiclePositionCommand] = []
        self.recorded_backfills: list[RecordBackfillPositionCommand] = []

    async def record_vehicle_position(self, command, *, uow):
        self.recorded_positions.append(command)

    async def record_backfill_position(self, command, *, uow):
        self.recorded_backfills.append(command)


class _FakeTripApplicationService:
    """`active_trip_id` is `None` by default (no active trip), matching the common case of a
    vehicle with no trip in progress - most tests never need to configure it."""

    def __init__(self, *, active_trip_id: str | None = None) -> None:
        self.active_trip_id = active_trip_id
        self.queries: list[GetActiveTripForVehicleQuery] = []

    async def get_active_trip_for_vehicle(self, query, *, uow):
        self.queries.append(query)
        if self.active_trip_id is None:
            return None
        return type("_TripDTO", (), {"id": self.active_trip_id})()


def _make_event(payload: dict, *, org_id: str | None = VALID_ORG_ULID) -> DomainEvent:
    return DomainEvent(
        event_id="evt-1",
        event_type="DevicePositionReported",
        version=1,
        occurred_at=datetime.now(timezone.utc),
        org_id=org_id,
        correlation_id=None,
        payload=payload,
        aggregate_type="Vehicle",
        aggregate_id="vehicle-1",
    )


class DevicePositionReportedProcessorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.container = Container()
        self.service = _RecordingTrackingService()
        self.trip_service = _FakeTripApplicationService()
        self.container.bind_singleton(TrackingApplicationService, self.service)
        self.container.bind_singleton(TrackingUnitOfWork, _FakeUnitOfWork())
        self.container.bind_singleton(TripApplicationService, self.trip_service)
        self.container.bind_singleton(TransportOpsUnitOfWork, _FakeUnitOfWork())
        self.processor = DevicePositionReportedProcessor(self.container)

    async def test_live_position_is_recorded_via_record_vehicle_position(self) -> None:
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "trip_id": None,
                "latitude": 22.672803,
                "longitude": 114.059395,
                "speed_kph": 12,
                "heading_deg": 270,
                "alarm_flags": 0,
                "event_time": "2026-07-24T10:00:00+00:00",
                "is_backfill": False,
            }
        )
        await self.processor.process(event)

        self.assertEqual(len(self.service.recorded_positions), 1)
        self.assertEqual(self.service.recorded_backfills, [])
        command = self.service.recorded_positions[0]
        self.assertEqual(command.organization_id, VALID_ORG_ULID)
        self.assertEqual(command.vehicle_id, "vehicle-1")
        self.assertEqual(command.device_id, "device-1")
        self.assertEqual(command.latitude, 22.672803)
        self.assertEqual(command.longitude, 114.059395)
        self.assertEqual(command.speed_kph, 12)
        self.assertEqual(command.heading_deg, 270)
        self.assertEqual(
            command.event_time, datetime(2026, 7, 24, 10, 0, 0, tzinfo=timezone.utc)
        )

    async def test_backfill_flagged_event_uses_record_backfill_position(self) -> None:
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": True,
            }
        )
        await self.processor.process(event)

        self.assertEqual(self.service.recorded_positions, [])
        self.assertEqual(len(self.service.recorded_backfills), 1)

    async def test_missing_optional_fields_default_to_none(self) -> None:
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
            }
        )
        await self.processor.process(event)

        command = self.service.recorded_positions[0]
        self.assertIsNone(command.trip_id)
        self.assertIsNone(command.speed_kph)
        self.assertIsNone(command.heading_deg)
        self.assertIsNone(command.alarm_flags)

    async def test_event_org_id_is_preferred_over_payload_organization_id(self) -> None:
        other_org = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"
        event = _make_event(
            {
                "organization_id": other_org,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
            },
            org_id=VALID_ORG_ULID,
        )
        await self.processor.process(event)

        self.assertEqual(
            self.service.recorded_positions[0].organization_id, VALID_ORG_ULID
        )

    async def test_live_position_resolves_trip_id_from_the_active_trip_service(self) -> None:
        """Roadmap A4: the payload's own (always-`None`-today) `trip_id` is never trusted for a
        live position - the resolved value from `TripApplicationService` wins unconditionally."""
        self.trip_service.active_trip_id = "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "trip_id": None,
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": False,
            }
        )
        await self.processor.process(event)

        self.assertEqual(
            self.service.recorded_positions[0].trip_id, "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        )
        self.assertEqual(len(self.trip_service.queries), 1)
        self.assertEqual(self.trip_service.queries[0].vehicle_id, "vehicle-1")

    async def test_resolved_trip_id_overrides_a_payload_trip_id_if_one_is_ever_present(
        self,
    ) -> None:
        """Even a hypothetical future vendor adapter that *does* attach its own `trip_id` must
        not win - the backend-resolved value is always authoritative (see this processor's own
        module docstring)."""
        self.trip_service.active_trip_id = "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "trip_id": "some-vendor-supplied-trip-id",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": False,
            }
        )
        await self.processor.process(event)

        self.assertEqual(
            self.service.recorded_positions[0].trip_id, "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        )

    async def test_no_active_trip_leaves_trip_id_none(self) -> None:
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": False,
            }
        )
        await self.processor.process(event)

        self.assertIsNone(self.service.recorded_positions[0].trip_id)

    async def test_backfill_position_never_resolves_active_trip_and_keeps_payload_value(
        self,
    ) -> None:
        """Roadmap A4's own carve-out: resolving "the vehicle's currently active trip" for a
        late-arriving, past-dated position would misattribute it - left unresolved instead."""
        self.trip_service.active_trip_id = "01J8Z3K9G6X8YV5T4N2R7QW3TR"
        event = _make_event(
            {
                "organization_id": VALID_ORG_ULID,
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "trip_id": "buffered-trip-id",
                "latitude": 22.0,
                "longitude": 114.0,
                "event_time": "2026-07-24T09:00:00+00:00",
                "is_backfill": True,
            }
        )
        await self.processor.process(event)

        self.assertEqual(self.service.recorded_backfills[0].trip_id, "buffered-trip-id")
        self.assertEqual(self.trip_service.queries, [])


if __name__ == "__main__":
    unittest.main()
