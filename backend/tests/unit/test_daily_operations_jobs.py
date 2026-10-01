"""The daily-operations worker jobs and the trip-cancellation notifier (ADR-0052..0054)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from raad.core.config.settings import Settings, WorkerSettings
from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.pagination import OffsetPage
from raad.core.time.clock import Clock
from raad.core.workers.scheduler import IntervalScheduler
from raad.interfaces.workers.bootstrap import _register_scheduled_jobs
from raad.interfaces.workers.daily_operations_jobs import (
    notify_uncovered_trips,
    uncovered_alert_text,
)
from raad.modules.notifications.events.subscribers import (
    StaffCoverCreatedNotifier,
    StaffSelfReportedUnavailabilityNotifier,
    TripCancelledNotifier,
)
from raad.modules.transport_ops.application.self_service import SelfServiceApplicationService
from raad.modules.transport_ops.application.operations_services import (
    DailyOperationsApplicationService,
)
from raad.modules.notifications.application.services import NotificationApplicationService
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import UncoveredTripAlertDTO

ORG = "01J8Z3K9G6X8YV5T4N2R7QW3MA"


def _alert(trip_id: str = "t1") -> UncoveredTripAlertDTO:
    return UncoveredTripAlertDTO(
        organization_id=ORG,
        trip_id=trip_id,
        scheduled_date=date(2026, 10, 1),
        trip_type="morning",
        vehicle_id="bus-1",
        route_name="North loop",
        driver_name="Amina",
        reason="driver_unavailable",
        key="driver_unavailable:d1",
    )


class _Ops:
    def __init__(self, alerts, today_counts=None) -> None:
        self.alerts = alerts
        self.today_counts = today_counts or {}
        self.marked: list[tuple[str, str]] = []

    async def collect_uncovered_alerts(self, *, uow):
        return list(self.alerts)

    async def mark_uncovered_alerted(self, trip_id, key, *, uow):
        self.marked.append((trip_id, key))

    async def uncovered_today(self, *, uow):
        return dict(self.today_counts)


class _User:
    def __init__(self, i):
        self.id = i


class _Users:
    def __init__(self, ids) -> None:
        self.ids = ids

    async def list_users(self, query, *, uow):
        return OffsetPage(data=[_User(i) for i in self.ids], total=len(self.ids), page=1, page_size=100)


class _Notes:
    def __init__(self) -> None:
        self.commands = []

    async def create_notification(self, command, *, uow):
        self.commands.append(command)


async def _run(ops, users, notes, hour: int = 10) -> int:
    return await notify_uncovered_trips(
        now=datetime(2026, 10, 1, hour, tzinfo=timezone.utc),
        summary_hour_utc=4,
        service=ops,  # type: ignore[arg-type]
        user_service=users,  # type: ignore[arg-type]
        notification_service=notes,  # type: ignore[arg-type]
        transport_ops_uow=lambda: object(),  # type: ignore[arg-type,return-value]
        iam_uow=lambda: object(),  # type: ignore[arg-type,return-value]
        notifications_uow=lambda: object(),  # type: ignore[arg-type,return-value]
    )


class UncoveredTripJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_admin_is_told_and_the_trip_is_marked(self) -> None:
        ops, notes = _Ops([_alert()]), _Notes()
        self.assertEqual(await _run(ops, _Users(["a1", "a2"]), notes), 1)
        self.assertEqual([c.recipient_user_id for c in notes.commands], ["a1", "a2"])
        self.assertEqual(notes.commands[0].data["kind"], "trip_uncovered")
        self.assertEqual(ops.marked, [("t1", "driver_unavailable:d1")])

    async def test_no_admin_leaves_the_alert_pending(self) -> None:
        ops, notes = _Ops([_alert()]), _Notes()
        self.assertEqual(await _run(ops, _Users([]), notes), 0)
        self.assertEqual((ops.marked, notes.commands), ([], []))

    async def test_summary_only_in_the_configured_hour(self) -> None:
        notes = _Notes()
        await _run(_Ops([], {ORG: 2}), _Users(["a1"]), notes, hour=10)
        self.assertEqual(notes.commands, [])
        await _run(_Ops([], {ORG: 2}), _Users(["a1"]), notes, hour=4)
        self.assertEqual(notes.commands[0].title, "2 trips uncovered today")

    def test_wording(self) -> None:
        title, body = uncovered_alert_text(_alert())
        self.assertEqual(title, "Morning trip on 2026-10-01 is uncovered")
        self.assertIn("its driver is unavailable (Amina)", body)


class _Clock(Clock):
    def now(self) -> datetime:
        return datetime(2026, 10, 1, tzinfo=timezone.utc)


class RegistrationTests(unittest.TestCase):
    def _names(self, settings: Settings) -> set[str]:
        scheduler = IntervalScheduler(_Clock())
        _register_scheduled_jobs(scheduler, Container(), settings)
        return {job.name for job in scheduler._jobs}

    def test_generation_is_opt_in_and_alerts_are_on_by_default(self) -> None:
        names = self._names(Settings())
        self.assertNotIn("generate_daily_trips", names)
        self.assertIn("notify_uncovered_trips", names)
        flipped = self._names(
            Settings(workers=WorkerSettings(auto_generate_trips=True, uncovered_trip_alerts=False))
        )
        self.assertIn("generate_daily_trips", flipped)
        self.assertNotIn("notify_uncovered_trips", flipped)


class _Trip:
    def __init__(self) -> None:
        from raad.modules.transport_ops.domain.value_objects import TripType

        self.organization_id = ORG
        self.trip_type = TripType.AFTERNOON
        self.scheduled_date = date(2026, 10, 2)
        self.cancelled_reason = "Bus broke down"


class _OpsForCancel:
    def __init__(self, trip, users) -> None:
        self.trip, self.users = trip, users

    async def parent_user_ids_for_trip(self, trip_id, *, uow):
        return self.trip, self.users


class _SelfService:
    def __init__(self, driver_user_id: str | None) -> None:
        self._driver_user_id = driver_user_id

    async def driver_user_id_for_trip(self, trip_id, *, uow):
        return None, self._driver_user_id

    async def user_id_for_staff(self, staff_id, *, uow):
        return self._driver_user_id


class _Admins:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    async def list_users(self, query, *, uow):
        return SimpleNamespace(data=[SimpleNamespace(id=i) for i in self._ids], total=len(self._ids))


def _staff_event(event_type: str, payload: dict) -> DomainEvent:
    return DomainEvent(
        event_id="01J8Z3K9G6X8YV5T4N2R7QW3EV",
        event_type=event_type,
        aggregate_type="StaffCover",
        aggregate_id="01J8Z3K9G6X8YV5T4N2R7QW3AG",
        org_id=ORG,
        occurred_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        payload=payload,
        version=1,
        correlation_id=None,
    )


class DriverNotifierTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0061: a substitute who can log in is told; the office is told when a driver reports
    their own unavailability, and only then."""

    def _container(self, notes, *, staff_user_id: str | None, admins: list[str] | None = None):
        from raad.modules.iam.application.ports import IamUnitOfWork
        from raad.modules.iam.application.services import UserApplicationService
        from raad.modules.notifications.application.ports import NotificationsUnitOfWork

        container = Container()
        container.bind_singleton(SelfServiceApplicationService, _SelfService(staff_user_id))
        container.bind_singleton(NotificationApplicationService, notes)
        container.bind_singleton(UserApplicationService, _Admins(admins or []))
        for uow_type in (TransportOpsUnitOfWork, NotificationsUnitOfWork, IamUnitOfWork):
            container.bind_factory(uow_type, lambda: object())
        return container

    async def test_a_substitute_driver_is_told_they_are_covering(self) -> None:
        notes = _Notes()
        await StaffCoverCreatedNotifier(self._container(notes, staff_user_id="d2")).process(
            _staff_event(
                "StaffCoverCreated",
                {"substitute_staff_id": "s2", "vehicle_id": "v1",
                 "starts_on": "2026-10-05", "ends_on": "2026-10-06"},
            )
        )
        (command,) = notes.commands
        self.assertEqual(command.recipient_user_id, "d2")
        self.assertEqual(command.data["kind"], "cover_assigned")
        self.assertIn("2026-10-05 to 2026-10-06", command.body)

    async def test_a_substitute_without_a_login_notifies_nobody(self) -> None:
        notes = _Notes()
        await StaffCoverCreatedNotifier(self._container(notes, staff_user_id=None)).process(
            _staff_event("StaffCoverCreated", {"substitute_staff_id": "s2",
                                               "starts_on": "2026-10-05", "ends_on": "2026-10-05"})
        )
        self.assertEqual(notes.commands, [])

    async def test_self_reported_unavailability_tells_the_office(self) -> None:
        notes = _Notes()
        container = self._container(notes, staff_user_id="d1", admins=["admin-1", "admin-2"])
        await StaffSelfReportedUnavailabilityNotifier(container).process(
            _staff_event(
                "StaffUnavailabilityRecorded",
                {"staff_id": "s1", "actor_id": "d1", "starts_on": "2026-10-05",
                 "ends_on": "2026-10-05", "reason": "sick"},
            )
        )
        self.assertEqual([c.recipient_user_id for c in notes.commands], ["admin-1", "admin-2"])
        self.assertEqual(notes.commands[0].data["kind"], "staff_unavailable")
        # The reason and the note are personal: neither reaches the notification.
        self.assertNotIn("sick", notes.commands[0].body)

    async def test_unavailability_recorded_by_the_office_notifies_nobody(self) -> None:
        notes = _Notes()
        container = self._container(notes, staff_user_id="d1", admins=["admin-1"])
        await StaffSelfReportedUnavailabilityNotifier(container).process(
            _staff_event(
                "StaffUnavailabilityRecorded",
                {"staff_id": "s1", "actor_id": "admin-1", "starts_on": "2026-10-05",
                 "ends_on": "2026-10-05", "reason": "sick"},
            )
        )
        self.assertEqual(notes.commands, [])


class TripCancelledNotifierTests(unittest.IsolatedAsyncioTestCase):
    def _container(self, ops, notes, driver_user_id: str | None = None) -> Container:
        container = Container()
        container.bind_singleton(DailyOperationsApplicationService, ops)
        container.bind_singleton(SelfServiceApplicationService, _SelfService(driver_user_id))
        container.bind_singleton(NotificationApplicationService, notes)
        container.bind_factory(TransportOpsUnitOfWork, lambda: object())
        from raad.modules.notifications.application.ports import NotificationsUnitOfWork

        container.bind_factory(NotificationsUnitOfWork, lambda: object())
        return container

    def _event(self) -> DomainEvent:
        return DomainEvent(
            event_id="01J8Z3K9G6X8YV5T4N2R7QW3EV",
            event_type="TripCancelled",
            aggregate_type="Trip",
            aggregate_id="01J8Z3K9G6X8YV5T4N2R7QW3TR",
            org_id=ORG,
            occurred_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            payload={"reason": "Bus broke down"},
            version=1,
            correlation_id=None,
        )

    async def test_every_linked_parent_is_told_with_the_reason(self) -> None:
        notes = _Notes()
        await TripCancelledNotifier(self._container(_OpsForCancel(_Trip(), ["p1", "p2"]), notes)).process(
            self._event()
        )
        self.assertEqual([c.recipient_user_id for c in notes.commands], ["p1", "p2"])
        self.assertEqual(notes.commands[0].title, "Your child's afternoon bus on 2026-10-02 is cancelled")
        self.assertIn("Reason: Bus broke down", notes.commands[0].body)
        self.assertEqual(notes.commands[0].data["kind"], "trip_cancelled")

    async def test_the_driver_is_told_too(self) -> None:
        """ADR-0061: the driver's phone is where a cancellation matters first."""
        notes = _Notes()
        container = self._container(_OpsForCancel(_Trip(), ["p1"]), notes, driver_user_id="d1")
        await TripCancelledNotifier(container).process(self._event())
        self.assertEqual([c.recipient_user_id for c in notes.commands], ["p1", "d1"])
        driver_note = notes.commands[1]
        self.assertEqual(driver_note.title, "Your afternoon trip on 2026-10-02 is cancelled")
        self.assertIn("Reason: Bus broke down", driver_note.body)
        self.assertEqual(driver_note.data["audience"], "driver")

    async def test_a_missing_trip_is_acknowledged_quietly(self) -> None:
        notes = _Notes()
        await TripCancelledNotifier(self._container(_OpsForCancel(None, []), notes)).process(self._event())
        self.assertEqual(notes.commands, [])


if __name__ == "__main__":
    unittest.main()
