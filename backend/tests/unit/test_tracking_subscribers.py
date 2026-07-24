"""Unit tests for `modules.tracking.events.subscribers` (roadmap track B2, ADR-0009). Stdlib
`unittest` — no `pytest`. Mirrors `test_notification_subscribers.py`'s convention: fakes bound
directly into a real `core.di.container.Container`, keyed by the real types
`DevicePositionReportedProcessor` resolves.

Covers: a live position event persists via `record_vehicle_position`; a backfill-flagged event
persists via `record_backfill_position` instead; optional fields (`trip_id`/`speed_kph`/
`heading_deg`/`alarm_flags`) pass through as `None` when absent from the payload, matching
`RecordVehiclePositionCommand`'s own optional fields; `event.org_id` is used over a payload
duplicate when both are present.
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
        self.container.bind_singleton(TrackingApplicationService, self.service)
        self.container.bind_singleton(TrackingUnitOfWork, _FakeUnitOfWork())
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


if __name__ == "__main__":
    unittest.main()
