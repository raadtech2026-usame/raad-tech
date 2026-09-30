"""Safety alerts (ADR-0055/0057) and the incident log (ADR-0056): domain rules, both application
services against in-memory fakes, and the two Notification Worker processors."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from _transport_staff_fakes import attach_staff_repositories
from raad.core.di.container import Container
from raad.core.errors.exceptions import DomainError, NotFoundError, RuleViolationError
from raad.core.events.base import DomainEvent
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import OffsetPage
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.services import UserApplicationService
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.services import NotificationApplicationService
from raad.modules.notifications.events.subscribers import (
    IncidentParentNoticeNotifier,
    SafetyAlertRaisedNotifier,
)
from raad.modules.tracking.application.commands import RecordDeviceAlarmCommand
from raad.modules.tracking.application.ports import ActiveTrip, ActiveTripPort, DeviceCommandPort, TrackingUnitOfWork
from raad.modules.tracking.application.safety_services import SafetyAlertApplicationService
from raad.modules.tracking.domain.repositories import SafetyAlertRepository
from raad.modules.transport_ops.application.incident_services import (
    IncidentApplicationService,
    ParentNotice,
    RecordIncidentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork, VehicleDirectoryPort
from raad.modules.transport_ops.domain.entities import Student, TransportStaff
from raad.modules.transport_ops.domain.value_objects import OrganizationId, StudentId, TransportStaffId

ORG = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
BUS = "01J8Z3K9G6X8YV5T4N2R7QW3VA"
NOW = datetime(2026, 10, 1, 7, tzinfo=timezone.utc)
ADMIN = Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=ORG)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


CLOCK = FixedClock()


class SequentialIds(IdGenerator):
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"01J8Z3K9G6X8YV5T4N2R{self._n:06d}"


# ---- tracking fakes -------------------------------------------------------------------------


class _Alerts(SafetyAlertRepository):
    def __init__(self) -> None:
        self.by_id: dict = {}

    async def get(self, alert_id):
        return self.by_id.get(str(alert_id))

    def add(self, alert) -> None:
        self.by_id[str(alert.id)] = alert

    async def find_open(self, vehicle_id, alarm_type):
        return next((a for a in self.by_id.values() if a.vehicle_id == vehicle_id and a.alarm_type == alarm_type and a.is_open), None)

    async def list_filtered(self, *, statuses=None, vehicle_id=None, alarm_type=None, start=None, end=None, limit=200):
        rows = [a for a in self.by_id.values() if not statuses or a.status.value in statuses]
        return sorted(rows, key=lambda a: a.raised_at, reverse=True)


class _TrackingUow(TrackingUnitOfWork):
    def __init__(self) -> None:
        self.safety_alerts = _Alerts()
        self.events: list = []

    def record_events(self, events) -> None:
        self.events.extend(events)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _Trips(ActiveTripPort):
    def __init__(self, trip: ActiveTrip | None = None) -> None:
        self.trip = trip

    async def active_trip_for_vehicle(self, vehicle_id):
        return self.trip


class _Commands(DeviceCommandPort):
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list = []

    async def confirm_alarm(self, *, terminal_id, alarm_type_mask):
        self.sent.append((terminal_id, alarm_type_mask))
        return self.ok


def _alarm(alarm_type: str = "sos", *, delay: timedelta = timedelta(seconds=2)) -> RecordDeviceAlarmCommand:
    return RecordDeviceAlarmCommand(
        organization_id=ORG,
        vehicle_id=BUS,
        device_id=None,
        terminal_id="00000000014482607571",
        alarm_type=alarm_type,
        event_time=NOW - delay,
        received_at=NOW,
        latitude=2.04,
        longitude=45.3,
        speed_kph=38.0,
    )


class SafetyAlertTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.uow = _TrackingUow()
        self.commands = _Commands()
        self.service = SafetyAlertApplicationService(
            clock=CLOCK, id_generator=SequentialIds(), active_trips=_Trips(ActiveTrip("trip-1", "driver-1")),
            device_commands=self.commands,
        )

    async def test_an_alarm_records_one_alert_with_its_trip_and_a_repeat_updates_it(self) -> None:
        first = await self.service.record_device_alarm(_alarm(), uow=self.uow)
        again = await self.service.record_device_alarm(_alarm(delay=timedelta(0)), uow=self.uow)
        self.assertEqual(first.id, again.id)
        self.assertEqual((again.occurrences, again.trip_id, again.driver_id, again.is_critical), (2, "trip-1", "driver-1", True))
        self.assertEqual([e.event_type for e in self.uow.events], ["SafetyAlertRaised"])  # a repeat is not news

    async def test_unknown_types_are_ignored_and_late_alarms_are_flagged(self) -> None:
        self.assertIsNone(await self.service.record_device_alarm(_alarm("teleport"), uow=self.uow))
        late = await self.service.record_device_alarm(_alarm("collision", delay=timedelta(minutes=30)), uow=self.uow)
        self.assertTrue(late.is_late)
        self.assertTrue(self.uow.events[-1].payload["is_late"])

    async def test_acknowledging_an_sos_confirms_it_on_the_terminal(self) -> None:
        alert = await self.service.record_device_alarm(_alarm(), uow=self.uow)
        acked = await self.service.acknowledge(alert.id, actor=ADMIN, uow=self.uow)
        self.assertEqual((acked.status, acked.device_confirmation), ("acknowledged", "requested"))
        self.assertEqual(self.commands.sent, [("00000000014482607571", 1)])

    async def test_no_broker_means_unconfirmed_not_failed(self) -> None:
        service = SafetyAlertApplicationService(clock=CLOCK, id_generator=SequentialIds(), active_trips=_Trips(), device_commands=None)
        alert = await service.record_device_alarm(_alarm(), uow=self.uow)
        acked = await service.acknowledge(alert.id, actor=ADMIN, uow=self.uow)
        self.assertEqual((acked.status, acked.device_confirmation), ("acknowledged", "unavailable"))

    async def test_other_types_are_not_confirmed_and_closed_alerts_stay_closed(self) -> None:
        alert = await self.service.record_device_alarm(_alarm("overspeed"), uow=self.uow)
        acked = await self.service.acknowledge(alert.id, actor=ADMIN, uow=self.uow)
        self.assertIsNone(acked.device_confirmation)
        self.assertEqual(self.commands.sent, [])
        await self.service.mark_false_alarm(alert.id, actor=ADMIN, uow=self.uow)
        with self.assertRaises(RuleViolationError):
            await self.service.resolve(alert.id, actor=ADMIN, uow=self.uow)
        again = await self.service.record_device_alarm(_alarm("overspeed"), uow=self.uow)
        self.assertNotEqual(again.id, alert.id)  # a closed alert is never reopened


# ---- incidents ------------------------------------------------------------------------------


class _Students:
    """Only the two calls the incident service makes."""

    def __init__(self) -> None:
        self.by_id: dict = {}

    async def get(self, student_id):
        return self.by_id.get(str(student_id))

    def add(self, student) -> None:
        self.by_id[str(student.id)] = student


class _Links:
    def __init__(self) -> None:
        self.links: list = []

    async def list_by_students(self, student_ids):
        wanted = {str(s) for s in student_ids}
        return [link for link in self.links if str(link.student_id) in wanted]


class _Parents:
    def __init__(self) -> None:
        self.by_id: dict = {}

    async def list_by_ids(self, ids):
        return [self.by_id[i] for i in ids if i in self.by_id]


class _Link:
    def __init__(self, student_id, parent_id) -> None:
        self.student_id, self.parent_id = student_id, parent_id


class _Parent:
    def __init__(self, user_id) -> None:
        self.user_id = user_id


class _TransportUow(TransportOpsUnitOfWork):
    def __init__(self) -> None:
        from test_daily_operations import _Drivers, _Routes, _Trips as _TripRepo

        self.drivers = _Drivers()
        self.routes = _Routes()
        self.trips = _TripRepo()
        self.students = _Students()
        self.student_parents = _Links()
        self.parents = _Parents()
        attach_staff_repositories(self)
        self.events: list = []

    def record_events(self, events) -> None:
        self.events.extend(events)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _Vehicles(VehicleDirectoryPort):
    async def organization_of_vehicle(self, vehicle_id):
        return {BUS: ORG}.get(vehicle_id)


class IncidentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ids = SequentialIds()
        self.uow = _TransportUow()
        self.service = IncidentApplicationService(clock=CLOCK, id_generator=self.ids, vehicle_directory=_Vehicles())
        self.child = Student.enroll(id=StudentId(self.ids.new_id()), organization_id=OrganizationId(ORG), full_name="Child", clock=CLOCK)
        self.uow.students.add(self.child)
        self.driver = TransportStaff.register(id=TransportStaffId(self.ids.new_id()), organization_id=OrganizationId(ORG), full_name="Amina", clock=CLOCK)
        self.uow.staff.add(self.driver)

    async def record(self, **overrides):
        values = dict(organization_id=ORG, category="medical", severity="high", occurred_at=NOW, title="Child fainted", actor=ADMIN)
        values.update(overrides)
        return await self.service.record(RecordIncidentCommand(**values), uow=self.uow)

    async def test_record_links_people_and_names_them(self) -> None:
        incident = await self.record(vehicle_id=BUS, staff_ids=(str(self.driver.id),), student_ids=(str(self.child.id),), description="Private")
        self.assertEqual((incident.staff_names, incident.student_names, incident.status), (["Amina"], ["Child"], "open"))
        event = self.uow.events[0]
        self.assertEqual(event.event_type, "IncidentRecorded")
        self.assertNotIn("Private", repr(event.payload))
        self.assertNotIn("fainted", repr(event.payload))

    async def test_links_elsewhere_are_not_found(self) -> None:
        for overrides in ({"vehicle_id": "01J8Z3K9G6X8YV5T4N2R7QW3VZ"}, {"student_ids": ("01J8Z3K9G6X8YV5T4N2R7QW3ZZ",)}):
            with self.subTest(**{k: str(v) for k, v in overrides.items()}), self.assertRaises(NotFoundError):
                await self.record(**overrides)

    async def test_status_flow_timeline_and_closing(self) -> None:
        incident = await self.record()
        await self.service.change_status(incident.id, "investigating", resolution=None, recorded_in_error=False, actor=ADMIN, uow=self.uow)
        with self.assertRaises(DomainError):
            await self.service.change_status(incident.id, "closed", resolution=None, recorded_in_error=False, actor=ADMIN, uow=self.uow)
        closed = await self.service.change_status(incident.id, "closed", resolution="Parents collected her", recorded_in_error=False, actor=ADMIN, uow=self.uow)
        self.assertEqual(closed.status, "closed")
        self.assertEqual([n.kind for n in closed.notes], ["status_change", "status_change"])
        with self.assertRaises(RuleViolationError):
            await self.service.change_status(incident.id, "open", resolution=None, recorded_in_error=False, actor=ADMIN, uow=self.uow)
        with self.assertRaises(RuleViolationError):
            await self.service.update(incident.id, {"severity": "low"}, actor=ADMIN, uow=self.uow)

    async def test_recorded_in_error_only_when_closing(self) -> None:
        incident = await self.record()
        with self.assertRaises(DomainError):
            await self.service.change_status(incident.id, "resolved", resolution=None, recorded_in_error=True, actor=ADMIN, uow=self.uow)
        closed = await self.service.change_status(incident.id, "closed", resolution="Wrong bus", recorded_in_error=True, actor=ADMIN, uow=self.uow)
        self.assertTrue(closed.recorded_in_error)

    async def test_parent_notice_needs_linked_students_and_reaches_their_parents(self) -> None:
        bare = await self.record()
        with self.assertRaises(DomainError):
            await self.service.notify_parents(bare.id, "Hello", actor=ADMIN, uow=self.uow)
        incident = await self.record(student_ids=(str(self.child.id),))
        self.uow.student_parents.links.append(_Link(self.child.id, "p1"))
        self.uow.parents.by_id["p1"] = _Parent("user-parent-1")
        notified = await self.service.notify_parents(incident.id, "She is fine now.", actor=ADMIN, uow=self.uow)
        note = notified.notes[-1]
        self.assertEqual(note.kind, "parent_notice")
        self.assertEqual(self.uow.events[-1].event_type, "IncidentParentNoticeSent")
        notice = await self.service.parent_notice(note.id, uow=self.uow)
        self.assertEqual((notice.message, notice.parent_user_ids), ("She is fine now.", ["user-parent-1"]))

    async def test_an_alert_becomes_a_critical_accident(self) -> None:
        from raad.modules.tracking.application.queries import SafetyAlertDTO

        alert = SafetyAlertDTO(
            id="01J8Z3K9G6X8YV5T4N2R7QW3AL", organization_id=ORG, vehicle_id=BUS, alarm_type="collision", is_critical=True,
            status="open", raised_at=NOW, last_raised_at=NOW, received_at=NOW, is_late=False, occurrences=1, latitude=None,
            longitude=None, speed_kph=None, trip_id=None, driver_id=None, incident_id=None, device_confirmation=None,
            acknowledged_at=None, closed_at=None,
        )
        incident = await self.service.record_from_alert(alert, actor=ADMIN, uow=self.uow)
        self.assertEqual((incident.category, incident.severity, incident.source_alert_id, incident.vehicle_id), ("accident", "critical", alert.id, BUS))


# ---- notifiers ---------------------------------------------------------------------------------


class _Notes:
    def __init__(self) -> None:
        self.commands: list = []

    async def create_notification(self, command, *, uow):
        self.commands.append(command)


class _Users:
    async def list_users(self, query, *, uow):
        class U:
            id = "admin-1"

        return OffsetPage(data=[U()], total=1, page=1, page_size=100)


class _IncidentsService:
    async def parent_notice(self, note_id, *, uow):
        return ParentNotice(organization_id=ORG, incident_id="inc-1", message="She is fine.", parent_user_ids=["p1", "p2"])


def _container(notes) -> Container:
    c = Container()
    c.bind_singleton(NotificationApplicationService, notes)
    c.bind_singleton(UserApplicationService, _Users())
    c.bind_singleton(IncidentApplicationService, _IncidentsService())
    for port in (NotificationsUnitOfWork, IamUnitOfWork, TransportOpsUnitOfWork):
        c.bind_factory(port, lambda: object())
    return c


def _event(event_type: str, payload: dict, aggregate_id: str = "01J8Z3K9G6X8YV5T4N2R7QW3AL") -> DomainEvent:
    return DomainEvent(event_id="01J8Z3K9G6X8YV5T4N2R7QW3EV", event_type=event_type, aggregate_type="X",
                       aggregate_id=aggregate_id, org_id=ORG, occurred_at=NOW, payload=payload, version=1, correlation_id=None)


class NotifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_live_critical_alarms_notify_admins(self) -> None:
        notes = _Notes()
        notifier = SafetyAlertRaisedNotifier(_container(notes))
        await notifier.process(_event("SafetyAlertRaised", {"alarm_type": "overspeed", "is_critical": False, "is_late": False}))
        await notifier.process(_event("SafetyAlertRaised", {"alarm_type": "sos", "is_critical": True, "is_late": True}))
        self.assertEqual(notes.commands, [])
        await notifier.process(_event("SafetyAlertRaised", {"alarm_type": "sos", "is_critical": True, "is_late": False, "vehicle_id": BUS}))
        [command] = notes.commands
        self.assertEqual((command.recipient_user_id, command.title, command.data["kind"]), ("admin-1", "SOS pressed on a bus", "safety_alert"))

    async def test_parent_notice_reaches_each_parent(self) -> None:
        notes = _Notes()
        await IncidentParentNoticeNotifier(_container(notes)).process(_event("IncidentParentNoticeSent", {}))
        self.assertEqual([c.recipient_user_id for c in notes.commands], ["p1", "p2"])
        self.assertEqual(notes.commands[0].body, "She is fine.")


if __name__ == "__main__":
    unittest.main()
