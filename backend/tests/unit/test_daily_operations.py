"""Daily transport operations (ADR-0052, ADR-0053, ADR-0054): domain rules and
`DailyOperationsApplicationService` against in-memory fakes."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

from _transport_staff_fakes import attach_staff_repositories
from raad.core.errors.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    RuleViolationError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    CancelTripCommand,
    CreateCoverCommand,
    GenerateTripsCommand,
    RecordClosureCommand,
    RecordUnavailabilityCommand,
    SaveTimetableEntryCommand,
)
from raad.modules.transport_ops.application.operations_services import (
    DailyOperationsApplicationService,
)
from raad.modules.transport_ops.application.ports import (
    TransportOpsUnitOfWork,
    VehicleDirectoryPort,
)
from raad.modules.transport_ops.application.services import TripApplicationService
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Route,
    RouteTimetableEntry,
    StaffUnavailability,
    TransportStaff,
    Trip,
    VehicleStaffAssignment,
)
from raad.modules.transport_ops.domain.repositories import (
    DriverRepository,
    RouteRepository,
    TripRepository,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    OrganizationId,
    RouteId,
    RouteStatus,
    RouteTimetableEntryId,
    StaffAssignmentKind,
    StaffUnavailabilityId,
    TransportStaffId,
    TransportStaffStatus,
    TripId,
    TripStatus,
    TripType,
    UnavailabilityReason,
    UserId,
    VehicleId,
    VehicleStaffAssignmentId,
)

ORG = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
BUS = "01J8Z3K9G6X8YV5T4N2R7QW3VA"
BUS_2 = "01J8Z3K9G6X8YV5T4N2R7QW3VB"
ROUTE = "01J8Z3K9G6X8YV5T4N2R7QW3RA"
# Wednesday 30 September 2026.
NOW = datetime(2026, 9, 30, 6, tzinfo=timezone.utc)
TODAY = NOW.date()


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


class _Drivers(DriverRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Driver] = {}

    async def get(self, driver_id):
        return self.by_id.get(str(driver_id))

    async def get_by_user_id(self, user_id):
        return None

    async def get_by_staff_id(self, staff_id):
        return next((d for d in self.by_id.values() if d.staff_id == staff_id), None)

    async def list_by_staff_ids(self, staff_ids):
        wanted = {str(s) for s in staff_ids}
        return [d for d in self.by_id.values() if str(d.staff_id) in wanted]

    async def list_by_ids(self, driver_ids):
        wanted = {str(i) for i in driver_ids}
        return [d for d in self.by_id.values() if str(d.id) in wanted]

    def add(self, driver):
        self.by_id[str(driver.id)] = driver

    async def list_all(self):
        return list(self.by_id.values())

    async def list_page(self, page_request, *, sort, filters, search):
        raise NotImplementedError


class _Routes(RouteRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Route] = {}

    async def get(self, route_id):
        return self.by_id.get(str(route_id))

    async def get_by_name(self, name):
        return None

    def add(self, route):
        self.by_id[str(route.id)] = route

    async def list_all(self):
        return list(self.by_id.values())

    async def list_page(self, page_request, *, sort, filters, search):
        raise NotImplementedError


class _Trips(TripRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Trip] = {}

    async def get(self, trip_id):
        return self.by_id.get(str(trip_id))

    def add(self, trip):
        self.by_id[str(trip.id)] = trip

    async def list_all(self):
        return list(self.by_id.values())

    async def list_between(self, start, end, *, vehicle_id=None):
        return sorted(
            (
                t
                for t in self.by_id.values()
                if start <= t.scheduled_date <= end and (vehicle_id is None or t.vehicle_id == vehicle_id)
            ),
            key=lambda t: (t.scheduled_date, t.trip_type.value),
        )

    async def active_trip_for_vehicle(self, vehicle_id):
        return None

    async def list_for_route(self, route_id):
        return []

    async def list_page(self, page_request, *, sort, filters, search):
        raise NotImplementedError


class FakeUow(TransportOpsUnitOfWork):
    def __init__(self) -> None:
        self.drivers = _Drivers()
        self.routes = _Routes()
        self.trips = _Trips()
        attach_staff_repositories(self)
        self.recorded_events: list = []
        self.commit_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        pass


class FakeVehicles(VehicleDirectoryPort):
    def __init__(self) -> None:
        self.owners = {BUS: ORG, BUS_2: ORG}

    async def organization_of_vehicle(self, vehicle_id):
        return self.owners.get(vehicle_id)


ADMIN = Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=ORG)


class OperationsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ids = SequentialIds()
        self.vehicles = FakeVehicles()
        self.service = DailyOperationsApplicationService(
            clock=CLOCK, id_generator=self.ids, vehicle_directory=self.vehicles
        )
        self.trip_service = TripApplicationService(clock=CLOCK, id_generator=self.ids)
        self.uow = FakeUow()
        route = Route(
            id=RouteId(ROUTE),
            organization_id=OrganizationId(ORG),
            name="North loop",
            status=RouteStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )
        self.uow.routes.add(route)
        self.amina = self.person("Amina Driver", driver=True)
        self.hassan = self.person("Hassan Driver", driver=True)
        self.fatima = self.person("Fatima Attendant")

    def person(self, name: str, *, driver: bool = False):
        staff = TransportStaff.register(
            id=TransportStaffId(self.ids.new_id()), organization_id=OrganizationId(ORG), full_name=name, clock=CLOCK
        )
        self.uow.staff.add(staff)
        driver_row = None
        if driver:
            driver_row = Driver.register(
                id=DriverId(self.ids.new_id()),
                organization_id=OrganizationId(ORG),
                user_id=UserId(self.ids.new_id()),
                license_no=f"DL-{name[:3]}",
                staff_id=staff.id,
                clock=CLOCK,
            )
            self.uow.drivers.add(driver_row)
        return staff, driver_row

    async def timetable(self, **overrides):
        values = dict(
            organization_id=ORG,
            route_id=ROUTE,
            vehicle_id=BUS,
            trip_type="morning",
            weekdays=(1, 2, 3, 4, 5),
            default_driver_id=str(self.amina[1].id),
            valid_from=TODAY,
            planned_departure=time(6, 45),
            actor=ADMIN,
        )
        values.update(overrides)
        return await self.service.save_timetable_entry(SaveTimetableEntryCommand(**values), uow=self.uow)

    async def generate(self, days: int = 7, **kw):
        return await self.service.generate_trips(GenerateTripsCommand(actor=ADMIN, days=days, **kw), uow=self.uow)

    async def unavailable(self, staff, start=TODAY, end=TODAY + timedelta(days=2)):
        return await self.service.record_unavailability(
            RecordUnavailabilityCommand(
                staff_id=str(staff.id), starts_on=start, ends_on=end, reason="sick", note="Flu", actor=ADMIN
            ),
            uow=self.uow,
        )


class DomainRuleTests(unittest.TestCase):
    def _trip(self, status=TripStatus.SCHEDULED) -> Trip:
        return Trip(
            id=TripId("01J8Z3K9G6X8YV5T4N2R7QW3TR"),
            organization_id=OrganizationId(ORG),
            vehicle_id=VehicleId(BUS),
            driver_id=DriverId("01J8Z3K9G6X8YV5T4N2R7QW3DR"),
            route_id=RouteId(ROUTE),
            trip_type=TripType.MORNING,
            status=status,
            scheduled_date=TODAY,
            started_at=None,
            ended_at=None,
            created_at=NOW,
            updated_at=NOW,
        )

    def test_only_a_scheduled_trip_can_be_cancelled_and_it_needs_a_reason(self) -> None:
        trip = self._trip()
        with self.assertRaises(DomainError):
            trip.cancel(reason="  ", clock=CLOCK)
        trip.cancel(reason="Bus broke down", clock=CLOCK)
        self.assertIs(trip.status, TripStatus.CANCELLED)
        self.assertEqual(trip.pull_domain_events()[-1].event_type, "TripCancelled")
        for status in (TripStatus.IN_PROGRESS, TripStatus.COMPLETED, TripStatus.CANCELLED):
            with self.subTest(status=status), self.assertRaises(RuleViolationError):
                self._trip(status).cancel(reason="x", clock=CLOCK)

    def test_timetable_entry_runs_on_its_weekdays_inside_its_validity(self) -> None:
        entry = RouteTimetableEntry.create(
            id=RouteTimetableEntryId("01J8Z3K9G6X8YV5T4N2R7QW3TT"),
            organization_id=OrganizationId(ORG),
            route_id=RouteId(ROUTE),
            vehicle_id=VehicleId(BUS),
            trip_type=TripType.MORNING,
            weekdays=(3, 1, 3),
            planned_departure=None,
            default_driver_id=DriverId("01J8Z3K9G6X8YV5T4N2R7QW3DR"),
            valid_from=TODAY,
            valid_until=TODAY + timedelta(days=7),
            clock=CLOCK,
        )
        self.assertEqual(entry.weekdays, (1, 3))
        self.assertTrue(entry.runs_on(TODAY))  # Wednesday
        self.assertFalse(entry.runs_on(TODAY + timedelta(days=1)))  # Thursday
        self.assertTrue(entry.runs_on(TODAY + timedelta(days=5)))  # Monday
        self.assertFalse(entry.runs_on(TODAY + timedelta(days=14)))  # past validity
        with self.assertRaises(DomainError):
            entry.update(clock=CLOCK, weekdays=(8,))

    def test_an_unavailability_is_withdrawn_not_deleted(self) -> None:
        item = StaffUnavailability.record(
            id=StaffUnavailabilityId("01J8Z3K9G6X8YV5T4N2R7QW3XA"),
            organization_id=OrganizationId(ORG),
            staff_id=TransportStaffId("01J8Z3K9G6X8YV5T4N2R7QW3SA"),
            starts_on=TODAY,
            ends_on=TODAY,
            reason=UnavailabilityReason.SICK,
            note="private",
            clock=CLOCK,
        )
        self.assertNotIn("private", repr(item.pull_domain_events()[0].payload))
        self.assertTrue(item.withdraw(clock=CLOCK))
        self.assertFalse(item.covers(TODAY))
        self.assertFalse(item.withdraw(clock=CLOCK))


class TimetableTests(OperationsTestCase):
    async def test_entry_names_its_route_and_driver(self) -> None:
        entry = await self.timetable()
        self.assertEqual((entry.route_name, entry.default_driver_name), ("North loop", "Amina Driver"))

    async def test_same_bus_period_and_weekday_is_a_clash(self) -> None:
        await self.timetable()
        with self.assertRaises(ConflictError):
            await self.timetable(weekdays=(5,), default_driver_id=str(self.hassan[1].id))
        await self.timetable(trip_type="afternoon")  # another period is fine
        await self.timetable(vehicle_id=BUS_2, default_driver_id=str(self.hassan[1].id))

    async def test_a_bus_elsewhere_is_not_found(self) -> None:
        self.vehicles.owners[BUS] = OTHER_ORG
        with self.assertRaises(NotFoundError):
            await self.timetable()


class GenerationTests(OperationsTestCase):
    async def test_generates_weekdays_only_and_is_idempotent(self) -> None:
        await self.timetable()
        preview = await self.generate(dry_run=True)
        self.assertEqual(preview.created, 0)
        self.assertEqual(self.uow.trips.by_id, {})
        # Wed 30 Sep .. Tue 6 Oct: Wed, Thu, Fri, Mon, Tue.
        self.assertEqual(len(preview.to_create), 5)
        result = await self.generate()
        self.assertEqual(result.created, 5)
        trip = next(iter(self.uow.trips.by_id.values()))
        self.assertEqual(trip.planned_departure, time(6, 45))
        self.assertIsNotNone(trip.timetable_entry_id)
        again = await self.generate()
        self.assertEqual((again.created, again.to_create), (0, []))

    async def test_closed_days_are_skipped(self) -> None:
        await self.timetable()
        await self.service.record_closure(
            RecordClosureCommand(
                organization_id=ORG, starts_on=TODAY, ends_on=TODAY + timedelta(days=1), label="Holiday", actor=ADMIN
            ),
            uow=self.uow,
        )
        result = await self.generate()
        self.assertEqual(result.created, 3)
        self.assertEqual(result.closed_days, [TODAY, TODAY + timedelta(days=1)])

    async def test_a_cancelled_trip_is_never_recreated(self) -> None:
        await self.timetable()
        await self.generate(days=1)
        trip = next(iter(self.uow.trips.by_id.values()))
        await self.trip_service.cancel_trip(
            CancelTripCommand(trip_id=str(trip.id), reason="Strike", actor=ADMIN), uow=self.uow
        )
        result = await self.generate(days=1)
        self.assertEqual(result.created, 0)

    async def test_an_inactive_default_driver_is_skipped_and_reported(self) -> None:
        await self.timetable()
        self.amina[1].disable(clock=CLOCK)
        result = await self.generate()
        self.assertEqual(result.created, 0)
        self.assertEqual({s.reason for s in result.skipped}, {"default_driver_inactive"})

    async def test_a_covered_absence_generates_with_the_substitute(self) -> None:
        await self.timetable()
        absence = await self.unavailable(self.amina[0], TODAY, TODAY)
        await self.service.create_cover(
            CreateCoverCommand(
                unavailability_id=absence.id, substitute_staff_id=str(self.hassan[0].id), vehicle_id=BUS, actor=ADMIN
            ),
            uow=self.uow,
        )
        result = await self.generate()
        first = next(p for p in result.to_create if p.scheduled_date == TODAY)
        self.assertEqual((first.driver_id, first.is_substitute), (str(self.hassan[1].id), True))
        others = [p for p in result.to_create if p.scheduled_date != TODAY]
        self.assertTrue(all(p.driver_id == str(self.amina[1].id) for p in others))

    async def test_manual_duplicate_trip_is_a_conflict(self) -> None:
        from raad.modules.transport_ops.application.commands import ScheduleTripCommand

        await self.timetable()
        await self.generate(days=1)
        with self.assertRaises(ConflictError):
            await self.trip_service.schedule_trip(
                ScheduleTripCommand(
                    organization_id=ORG,
                    vehicle_id=BUS,
                    driver_id=str(self.hassan[1].id),
                    route_id=ROUTE,
                    trip_type="morning",
                    scheduled_date=TODAY,
                    actor=ADMIN,
                ),
                uow=self.uow,
            )


class CoverAndBoardTests(OperationsTestCase):
    async def asyncSetUp(self) -> None:
        await self.timetable()
        await self.generate(days=3)
        crew = VehicleStaffAssignment.assign(
            id=VehicleStaffAssignmentId(self.ids.new_id()),
            organization_id=OrganizationId(ORG),
            staff_id=self.fatima[0].id,
            vehicle_id=VehicleId(BUS),
            role_id=None,
            route_id=None,
            starts_on=TODAY - timedelta(days=30),
            ends_on=None,
            kind=StaffAssignmentKind.PERMANENT,
            reason=None,
            clock=CLOCK,
        )
        self.uow.staff_assignments.add(crew)

    def today_trip(self) -> Trip:
        return next(t for t in self.uow.trips.by_id.values() if t.scheduled_date == TODAY)

    async def test_an_absent_driver_makes_the_trip_uncovered_until_covered(self) -> None:
        absence = await self.unavailable(self.amina[0])
        board = await self.service.daily_board(TODAY, uow=self.uow)
        self.assertEqual(board.uncovered_trips, 1)
        self.assertEqual(board.vehicles[0].trips[0].uncovered_reason, "driver_unavailable")

        cover = await self.service.create_cover(
            CreateCoverCommand(
                unavailability_id=absence.id, substitute_staff_id=str(self.hassan[0].id), vehicle_id=BUS, actor=ADMIN
            ),
            uow=self.uow,
        )
        self.assertEqual(cover.trips_reassigned, 3)
        self.assertEqual(self.today_trip().driver_id, self.hassan[1].id)
        board = await self.service.daily_board(TODAY, uow=self.uow)
        self.assertEqual(board.uncovered_trips, 0)
        names = {c.staff_name: c for c in board.vehicles[0].crew}
        self.assertTrue(names["Hassan Driver"].is_substitute)

    async def test_a_driver_cover_needs_active_driver_access(self) -> None:
        absence = await self.unavailable(self.amina[0])
        with self.assertRaises(DomainError):
            await self.service.create_cover(
                CreateCoverCommand(
                    unavailability_id=absence.id, substitute_staff_id=str(self.fatima[0].id), vehicle_id=BUS, actor=ADMIN
                ),
                uow=self.uow,
            )

    async def test_withdrawing_the_unavailability_restores_the_driver(self) -> None:
        absence = await self.unavailable(self.amina[0])
        await self.service.create_cover(
            CreateCoverCommand(
                unavailability_id=absence.id, substitute_staff_id=str(self.hassan[0].id), vehicle_id=BUS, actor=ADMIN
            ),
            uow=self.uow,
        )
        withdrawn = await self.service.withdraw_unavailability(absence.id, actor=ADMIN, uow=self.uow)
        self.assertIsNotNone(withdrawn.withdrawn_at)
        self.assertIsNotNone(withdrawn.covers[0].withdrawn_at)
        self.assertEqual(self.today_trip().driver_id, self.amina[1].id)

    async def test_an_absent_attendant_is_a_crew_gap_not_an_uncovered_trip(self) -> None:
        await self.unavailable(self.fatima[0])
        board = await self.service.daily_board(TODAY, uow=self.uow)
        self.assertEqual((board.uncovered_trips, board.vehicles[0].crew_gaps), (0, 1))

    async def test_a_driver_who_left_leaves_trips_uncovered(self) -> None:
        self.amina[0].change_status(TransportStaffStatus.LEFT, clock=CLOCK)
        board = await self.service.daily_board(TODAY, uow=self.uow)
        self.assertEqual(board.vehicles[0].trips[0].uncovered_reason, "driver_not_active")

    async def test_uncovered_alerts_fire_once_per_cause_and_reset_when_covered(self) -> None:
        absence = await self.unavailable(self.amina[0])
        alerts = await self.service.collect_uncovered_alerts(uow=self.uow)
        self.assertEqual(len(alerts), 2)  # today and tomorrow
        for alert in alerts:
            await self.service.mark_uncovered_alerted(alert.trip_id, alert.key, uow=self.uow)
        self.assertEqual(await self.service.collect_uncovered_alerts(uow=self.uow), [])
        await self.service.withdraw_unavailability(absence.id, actor=ADMIN, uow=self.uow)
        self.assertEqual(await self.service.collect_uncovered_alerts(uow=self.uow), [])
        self.assertIsNone(self.today_trip().coverage_alert_key)
        await self.unavailable(self.amina[0])
        self.assertEqual(len(await self.service.collect_uncovered_alerts(uow=self.uow)), 2)
        self.assertEqual(await self.service.uncovered_today(uow=self.uow), {ORG: 1})

    async def test_cancelled_trips_are_never_uncovered(self) -> None:
        await self.unavailable(self.amina[0])
        await self.trip_service.cancel_trip(
            CancelTripCommand(trip_id=str(self.today_trip().id), reason="Closed", actor=ADMIN), uow=self.uow
        )
        board = await self.service.daily_board(TODAY, uow=self.uow)
        self.assertEqual(board.uncovered_trips, 0)
        self.assertEqual(board.vehicles[0].trips[0].status, "cancelled")


if __name__ == "__main__":
    unittest.main()
