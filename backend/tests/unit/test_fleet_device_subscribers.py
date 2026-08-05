"""Unit tests for `modules.fleet_device.events.subscribers` (`docs/architecture/
post-f7-production-readiness-roadmap.md` Phase A item A3). Stdlib `unittest` - no `pytest`.
Mirrors `test_tracking_subscribers.py`'s convention: fakes bound directly into a real
`core.di.container.Container`, keyed by the real types `DeviceConnectivityProcessor` resolves.

Covers: `DeviceOnline`/`DeviceOffline` both call `record_device_seen` with `event.occurred_at`
(not a payload field - neither event's payload carries a timestamp) and `SYSTEM_PRINCIPAL`; a
missing/`None` `device_id` in the payload is dropped, not passed through as `None`.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.modules.fleet_device.application.commands import RecordDeviceSeenCommand
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import DeviceApplicationService
from raad.modules.fleet_device.events.subscribers import (
    SYSTEM_PRINCIPAL,
    DeviceConnectivityProcessor,
)

_OCCURRED_AT = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


class _FakeUnitOfWork:
    """`Container.resolve` is a plain type-keyed lookup with no `isinstance` enforcement (see
    `test_tracking_subscribers.py`'s identical precedent) - the fake service below never
    actually uses `uow`."""


class _RecordingDeviceApplicationService:
    def __init__(self) -> None:
        self.recorded: list[RecordDeviceSeenCommand] = []

    async def record_device_seen(self, command: RecordDeviceSeenCommand, *, uow) -> None:
        self.recorded.append(command)


def _make_event(
    *, event_type: str, payload: dict, occurred_at: datetime = _OCCURRED_AT
) -> DomainEvent:
    return DomainEvent(
        event_id="evt-1",
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=payload.get("organization_id"),
        correlation_id=None,
        payload=payload,
        aggregate_type="Device",
        aggregate_id="00007",
    )


class DeviceConnectivityProcessorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.container = Container()
        self.service = _RecordingDeviceApplicationService()
        self.container.bind_singleton(DeviceApplicationService, self.service)
        self.container.bind_singleton(FleetDeviceUnitOfWork, _FakeUnitOfWork())

    async def test_device_online_records_seen_with_event_occurred_at(self) -> None:
        processor = DeviceConnectivityProcessor("DeviceOnline", self.container)
        event = _make_event(
            event_type="DeviceOnline",
            payload={
                "organization_id": "org-1",
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "terminal_id": "00007",
            },
        )

        await processor.process(event)

        self.assertEqual(len(self.service.recorded), 1)
        command = self.service.recorded[0]
        self.assertEqual(command.device_id, "device-1")
        self.assertEqual(command.seen_at, _OCCURRED_AT)
        self.assertTrue(command.is_online)
        self.assertIs(command.actor, SYSTEM_PRINCIPAL)

    async def test_device_offline_also_records_seen(self) -> None:
        """A `DeviceOffline` still records the timestamp `devices.last_seen_at` should carry -
        "when was this device last seen" is true regardless of which direction the transition
        went (see this processor's own class docstring)."""
        processor = DeviceConnectivityProcessor("DeviceOffline", self.container)
        event = _make_event(
            event_type="DeviceOffline",
            payload={
                "organization_id": "org-1",
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "terminal_id": "00007",
                "reason": "session_expired",
            },
        )

        await processor.process(event)

        self.assertEqual(len(self.service.recorded), 1)
        self.assertEqual(self.service.recorded[0].device_id, "device-1")
        # ADR-0020 §3: DeviceOffline must record is_online=False, not just a timestamp.
        self.assertFalse(self.service.recorded[0].is_online)

    async def test_missing_device_id_is_dropped_not_passed_through(self) -> None:
        processor = DeviceConnectivityProcessor("DeviceOnline", self.container)
        event = _make_event(
            event_type="DeviceOnline",
            payload={
                "organization_id": None,
                "vehicle_id": None,
                "device_id": None,
                "terminal_id": "00007",
            },
        )

        await processor.process(event)

        self.assertEqual(self.service.recorded, [])

    async def test_event_type_matches_the_constructor_argument(self) -> None:
        online = DeviceConnectivityProcessor("DeviceOnline", self.container)
        offline = DeviceConnectivityProcessor("DeviceOffline", self.container)
        self.assertEqual(online.event_type, "DeviceOnline")
        self.assertEqual(offline.event_type, "DeviceOffline")


if __name__ == "__main__":
    unittest.main()
