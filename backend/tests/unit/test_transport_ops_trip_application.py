"""Application-layer tests for `transport_ops`'s `TripApplicationService` (Phase 12). Stdlib
`unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_route_application.py`/`test_transport_ops_student_parent_application.py`'s
exact structure. Uses in-memory fakes for `TripRepository`/`DriverRepository`/`RouteRepository`,
bundled onto one fake `TransportOpsUnitOfWork` — no SQLAlchemy, no FastAPI, no real database.
Covers: command immutability, DTO mapping, schedule/start/end/interrupt/resume/change-driver
orchestration, `ensure_driver_exists`/`ensure_route_exists` not-found paths,
`ensure_vehicle_has_no_active_trip`'s `ConflictError` on both `start_trip` and `resume_trip`,
and the read paths.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import date, datetime, timezone

from raad.core.errors.exceptions import ConflictError, DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import FilterCondition, OffsetPage, OffsetPageRequest, SortSpec
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    ChangeTripDriverCommand,
    EndTripCommand,
    InterruptTripCommand,
    ResumeTripCommand,
    ScheduleTripCommand,
    StartTripCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetTripByIdQuery,
    ListTripsQuery,
    TripDTO,
    TripSummaryDTO,
    trip_to_dto,
    trip_to_summary_dto,
)
from raad.modules.transport_ops.application.services import TripApplicationService
from raad.modules.transport_ops.domain.entities import Driver, Route, Trip
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
    TripId,
    TripStatus,
    TripType,
    UserId,
    VehicleId,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ZY"
VALID_VEHICLE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3VE"
VALID_DRIVER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3DR"
OTHER_DRIVER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3D2"
VALID_ROUTE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3RT"
NON_EXISTENT_DRIVER_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"
NON_EXISTENT_ROUTE_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZX"
NON_EXISTENT_TRIP_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZW"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequentialIdGenerator(IdGenerator):
    """26-char, valid-Crockford-Base32 ULID-shaped ids, unique per call - mirrors
    `test_transport_ops_route_application.py`'s identical helper exactly."""

    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def _field_text(item: object, field_name: str) -> str:
    value = getattr(item, field_name)
    value = getattr(value, "value", value)
    return "" if value is None else str(value)


def _matches_filter(item: object, condition: FilterCondition) -> bool:
    text = _field_text(item, condition.field)
    if condition.op == "eq":
        return text == condition.value
    if condition.op == "in":
        return text in {part.strip() for part in condition.value.split(",")}
    if condition.op == "gte":
        return text >= condition.value
    if condition.op == "lte":
        return text <= condition.value
    if condition.op == "gt":
        return text > condition.value
    if condition.op == "lt":
        return text < condition.value
    return True


def _paginate_in_memory(
    items: list,
    page_request: OffsetPageRequest,
    *,
    sort: list[SortSpec],
    filters: list[FilterCondition],
    search: str | None,
    search_field: str = "scheduled_date",
) -> OffsetPage:
    """Shared in-memory equivalent of `SqlAlchemyRepositoryBase.list_page` (`core/db/
    repository.py`), for fake repositories that can't run real SQL — duplicated per module's
    own test file rather than a shared test helper, mirroring
    `test_organization_application.py`'s own established "duplicated per module" precedent.
    `Trip` has no `searchable_fields` whitelist (`infra/repositories.py`'s Tier 2 pagination
    phase addition) — `search_field`/`search` are accepted for shape-parity with every other
    module's identical helper but are never exercised by this file's own tests."""
    for condition in filters:
        items = [item for item in items if _matches_filter(item, condition)]
    if search:
        items = [
            item
            for item in items
            if search.lower() in _field_text(item, search_field).lower()
        ]
    for spec in reversed(sort):
        items = sorted(
            items, key=lambda item: _field_text(item, spec.field), reverse=spec.descending
        )
    if not sort:
        items = sorted(items, key=lambda item: str(item.id))
    total = len(items)
    start = page_request.offset
    end = start + page_request.page_size
    return OffsetPage(
        data=items[start:end], total=total, page=page_request.page, page_size=page_request.page_size
    )


class InMemoryTripRepository(TripRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Trip] = {}

    async def get(self, trip_id: TripId) -> Trip | None:
        return self.by_id.get(str(trip_id))

    def add(self, trip: Trip) -> None:
        self.by_id[str(trip.id)] = trip

    async def list_all(self) -> list[Trip]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Trip]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )

    async def active_trip_for_vehicle(self, vehicle_id: VehicleId) -> Trip | None:
        return next(
            (
                trip
                for trip in self.by_id.values()
                if str(trip.vehicle_id) == str(vehicle_id)
                and trip.status == TripStatus.IN_PROGRESS
            ),
            None,
        )

    async def list_for_route(self, route_id: RouteId) -> list[Trip]:
        return [
            trip for trip in self.by_id.values() if str(trip.route_id) == str(route_id)
        ]


class InMemoryDriverRepository(DriverRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Driver] = {}

    async def get(self, driver_id: DriverId) -> Driver | None:
        return self.by_id.get(str(driver_id))

    def add(self, driver: Driver) -> None:
        self.by_id[str(driver.id)] = driver

    async def list_all(self) -> list[Driver]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Driver]:
        # Not this file's own listing focus (see `test_transport_ops_driver_application.py`
        # for `Driver`'s dedicated pagination tests) - only implemented here because
        # `DriverRepository` is an ABC `TripApplicationService`'s tests must still construct.
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
            search_field="license_no",
        )


class InMemoryRouteRepository(RouteRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Route] = {}

    async def get(self, route_id: RouteId) -> Route | None:
        return self.by_id.get(str(route_id))

    async def get_by_name(self, name: str) -> Route | None:
        return next((r for r in self.by_id.values() if r.name == name), None)

    def add(self, route: Route) -> None:
        self.by_id[str(route.id)] = route

    async def list_all(self) -> list[Route]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Route]:
        # Not this file's own listing focus (see `test_transport_ops_route_application.py`
        # for `Route`'s dedicated pagination tests) - only implemented here because
        # `RouteRepository` is an ABC `TripApplicationService`'s tests must still construct.
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
            search_field="name",
        )


class FakeTransportOpsUnitOfWork(TransportOpsUnitOfWork):
    def __init__(
        self,
        trips: InMemoryTripRepository,
        drivers: InMemoryDriverRepository,
        routes: InMemoryRouteRepository,
    ) -> None:
        self.trips = trips
        self.drivers = drivers
        self.routes = routes
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def make_actor(org_id: str = VALID_ORG_ULID) -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=org_id)


def make_driver(
    driver_id: str = VALID_DRIVER_ULID, organization_id: str = VALID_ORG_ULID
) -> Driver:
    return Driver(
        id=DriverId(driver_id),
        organization_id=OrganizationId(organization_id),
        user_id=UserId("01J8Z3K9G6X8YV5T4N2R7QW3US"),
        license_no="LIC-001",
        status=DriverStatus.ACTIVE,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def make_route(
    route_id: str = VALID_ROUTE_ULID, organization_id: str = VALID_ORG_ULID
) -> Route:
    return Route(
        id=RouteId(route_id),
        organization_id=OrganizationId(organization_id),
        name="Morning Route A",
        status=RouteStatus.ACTIVE,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def make_service() -> tuple[TripApplicationService, FakeTransportOpsUnitOfWork]:
    clock = FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    service = TripApplicationService(clock=clock, id_generator=id_generator)
    uow = FakeTransportOpsUnitOfWork(
        InMemoryTripRepository(), InMemoryDriverRepository(), InMemoryRouteRepository()
    )
    return service, uow


def seed_driver_and_route(uow: FakeTransportOpsUnitOfWork) -> None:
    uow.drivers.add(make_driver())
    uow.routes.add(make_route())


class CommandImmutabilityTests(unittest.TestCase):
    def test_schedule_command_is_frozen(self) -> None:
        command = ScheduleTripCommand(
            organization_id=VALID_ORG_ULID,
            vehicle_id=VALID_VEHICLE_ULID,
            driver_id=VALID_DRIVER_ULID,
            route_id=VALID_ROUTE_ULID,
            trip_type="morning",
            scheduled_date=date(2026, 7, 20),
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.vehicle_id = "other-vehicle"  # type: ignore[misc]

    def test_lifecycle_commands_are_frozen(self) -> None:
        for command in (
            StartTripCommand(trip_id="t1", actor=make_actor()),
            EndTripCommand(trip_id="t1", actor=make_actor()),
            ResumeTripCommand(trip_id="t1", actor=make_actor()),
        ):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                command.trip_id = "other-id"  # type: ignore[misc]

    def test_commands_carry_the_actor_principal(self) -> None:
        actor = make_actor()
        command = StartTripCommand(trip_id="t1", actor=actor)
        self.assertIs(command.actor, actor)


class DTOMappingTests(unittest.TestCase):
    def make_trip(self) -> Trip:
        return Trip(
            id=TripId("01J8Z3K9G6X8YV5T4N2R7QW3T1"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            driver_id=DriverId(VALID_DRIVER_ULID),
            route_id=RouteId(VALID_ROUTE_ULID),
            trip_type=TripType.MORNING,
            status=TripStatus.SCHEDULED,
            scheduled_date=date(2026, 7, 20),
            started_at=None,
            ended_at=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_trip_to_dto_maps_all_fields_as_primitives(self) -> None:
        dto = trip_to_dto(self.make_trip())
        self.assertIsInstance(dto, TripDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3T1")
        self.assertEqual(dto.vehicle_id, VALID_VEHICLE_ULID)
        self.assertEqual(dto.trip_type, "morning")  # enum -> .value
        self.assertEqual(dto.status, "scheduled")
        self.assertEqual(dto.scheduled_date, date(2026, 7, 20))

    def test_trip_to_summary_dto_maps_reduced_field_set(self) -> None:
        dto = trip_to_summary_dto(self.make_trip())
        self.assertIsInstance(dto, TripSummaryDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3T1")
        self.assertFalse(hasattr(dto, "organization_id"))

    def test_dtos_are_frozen(self) -> None:
        dto = trip_to_dto(self.make_trip())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dto.status = "in_progress"  # type: ignore[misc]


class ScheduleTripTests(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_trip_adds_to_repository_and_commits(self) -> None:
        service, uow = make_service()
        seed_driver_and_route(uow)
        command = ScheduleTripCommand(
            organization_id=VALID_ORG_ULID,
            vehicle_id=VALID_VEHICLE_ULID,
            driver_id=VALID_DRIVER_ULID,
            route_id=VALID_ROUTE_ULID,
            trip_type="morning",
            scheduled_date=date(2026, 7, 20),
            actor=make_actor(),
        )
        dto = await service.schedule_trip(command, uow=uow)

        self.assertEqual(dto.status, "scheduled")
        self.assertEqual(len(uow.trips.by_id), 1)
        self.assertEqual(uow.commit_count, 1)

    async def test_schedule_trip_records_domain_events(self) -> None:
        service, uow = make_service()
        seed_driver_and_route(uow)
        command = ScheduleTripCommand(
            organization_id=VALID_ORG_ULID,
            vehicle_id=VALID_VEHICLE_ULID,
            driver_id=VALID_DRIVER_ULID,
            route_id=VALID_ROUTE_ULID,
            trip_type="morning",
            scheduled_date=date(2026, 7, 20),
            actor=make_actor(),
        )
        await service.schedule_trip(command, uow=uow)
        self.assertEqual(len(uow.recorded_events), 1)
        self.assertEqual(uow.recorded_events[0].event_type, "TripScheduled")

    async def test_schedule_trip_with_nonexistent_driver_raises_not_found_error(
        self,
    ) -> None:
        service, uow = make_service()
        uow.routes.add(make_route())
        command = ScheduleTripCommand(
            organization_id=VALID_ORG_ULID,
            vehicle_id=VALID_VEHICLE_ULID,
            driver_id=NON_EXISTENT_DRIVER_ID,
            route_id=VALID_ROUTE_ULID,
            trip_type="morning",
            scheduled_date=date(2026, 7, 20),
            actor=make_actor(),
        )
        with self.assertRaises(NotFoundError):
            await service.schedule_trip(command, uow=uow)

    async def test_schedule_trip_with_nonexistent_route_raises_not_found_error(
        self,
    ) -> None:
        service, uow = make_service()
        uow.drivers.add(make_driver())
        command = ScheduleTripCommand(
            organization_id=VALID_ORG_ULID,
            vehicle_id=VALID_VEHICLE_ULID,
            driver_id=VALID_DRIVER_ULID,
            route_id=NON_EXISTENT_ROUTE_ID,
            trip_type="morning",
            scheduled_date=date(2026, 7, 20),
            actor=make_actor(),
        )
        with self.assertRaises(NotFoundError):
            await service.schedule_trip(command, uow=uow)

    async def test_schedule_trip_with_cross_organization_driver_raises_domain_error(
        self,
    ) -> None:
        service, uow = make_service()
        uow.drivers.add(make_driver(organization_id=OTHER_ORG_ULID))
        uow.routes.add(make_route())
        command = ScheduleTripCommand(
            organization_id=VALID_ORG_ULID,
            vehicle_id=VALID_VEHICLE_ULID,
            driver_id=VALID_DRIVER_ULID,
            route_id=VALID_ROUTE_ULID,
            trip_type="morning",
            scheduled_date=date(2026, 7, 20),
            actor=make_actor(),
        )
        with self.assertRaises(DomainError):
            await service.schedule_trip(command, uow=uow)


class TripLifecycleOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def _scheduled_trip_dto(
        self, service: TripApplicationService, uow: FakeTransportOpsUnitOfWork
    ) -> TripDTO:
        seed_driver_and_route(uow)
        command = ScheduleTripCommand(
            organization_id=VALID_ORG_ULID,
            vehicle_id=VALID_VEHICLE_ULID,
            driver_id=VALID_DRIVER_ULID,
            route_id=VALID_ROUTE_ULID,
            trip_type="morning",
            scheduled_date=date(2026, 7, 20),
            actor=make_actor(),
        )
        return await service.schedule_trip(command, uow=uow)

    async def test_start_trip_transitions_to_in_progress(self) -> None:
        service, uow = make_service()
        trip = await self._scheduled_trip_dto(service, uow)
        dto = await service.start_trip(
            StartTripCommand(trip_id=trip.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "in_progress")

    async def test_start_trip_rejects_when_vehicle_already_has_active_trip(
        self,
    ) -> None:
        service, uow = make_service()
        trip = await self._scheduled_trip_dto(service, uow)
        await service.start_trip(
            StartTripCommand(trip_id=trip.id, actor=make_actor()), uow=uow
        )

        # A second trip for the same vehicle.
        second = Trip.schedule(
            id=TripId("01J8Z3K9G6X8YV5T4N2R7QW3T9"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            driver_id=DriverId(VALID_DRIVER_ULID),
            driver_organization_id=OrganizationId(VALID_ORG_ULID),
            route_id=RouteId(VALID_ROUTE_ULID),
            route_organization_id=OrganizationId(VALID_ORG_ULID),
            trip_type=TripType.AFTERNOON,
            scheduled_date=date(2026, 7, 20),
            clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        )
        uow.trips.add(second)

        with self.assertRaises(ConflictError):
            await service.start_trip(
                StartTripCommand(trip_id=str(second.id), actor=make_actor()), uow=uow
            )

    async def test_end_trip_transitions_to_completed(self) -> None:
        service, uow = make_service()
        trip = await self._scheduled_trip_dto(service, uow)
        await service.start_trip(
            StartTripCommand(trip_id=trip.id, actor=make_actor()), uow=uow
        )
        dto = await service.end_trip(
            EndTripCommand(trip_id=trip.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "completed")

    async def test_interrupt_then_resume_round_trips_to_in_progress(self) -> None:
        service, uow = make_service()
        trip = await self._scheduled_trip_dto(service, uow)
        await service.start_trip(
            StartTripCommand(trip_id=trip.id, actor=make_actor()), uow=uow
        )
        interrupted = await service.interrupt_trip(
            InterruptTripCommand(
                trip_id=trip.id, reason="device offline", actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(interrupted.status, "interrupted")

        resumed = await service.resume_trip(
            ResumeTripCommand(trip_id=trip.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(resumed.status, "in_progress")

    async def test_resume_trip_rejects_when_vehicle_gained_another_active_trip(
        self,
    ) -> None:
        """The edge case `application/services.py`'s module docstring documents: a different
        trip for the same vehicle can legally become IN_PROGRESS while this one sits
        INTERRUPTED - resuming must not silently create two active trips for one vehicle."""
        service, uow = make_service()
        trip = await self._scheduled_trip_dto(service, uow)
        await service.start_trip(
            StartTripCommand(trip_id=trip.id, actor=make_actor()), uow=uow
        )
        await service.interrupt_trip(
            InterruptTripCommand(trip_id=trip.id, reason="timeout", actor=make_actor()),
            uow=uow,
        )

        other = Trip.schedule(
            id=TripId("01J8Z3K9G6X8YV5T4N2R7QW3T8"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            driver_id=DriverId(VALID_DRIVER_ULID),
            driver_organization_id=OrganizationId(VALID_ORG_ULID),
            route_id=RouteId(VALID_ROUTE_ULID),
            route_organization_id=OrganizationId(VALID_ORG_ULID),
            trip_type=TripType.AFTERNOON,
            scheduled_date=date(2026, 7, 20),
            clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        )
        other.start(clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)))
        uow.trips.add(other)

        with self.assertRaises(ConflictError):
            await service.resume_trip(
                ResumeTripCommand(trip_id=trip.id, actor=make_actor()), uow=uow
            )

    async def test_change_trip_driver_updates_driver(self) -> None:
        service, uow = make_service()
        trip = await self._scheduled_trip_dto(service, uow)
        uow.drivers.add(make_driver(driver_id=OTHER_DRIVER_ULID))

        dto = await service.change_trip_driver(
            ChangeTripDriverCommand(
                trip_id=trip.id, driver_id=OTHER_DRIVER_ULID, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(dto.driver_id, OTHER_DRIVER_ULID)

    async def test_change_trip_driver_with_nonexistent_driver_raises_not_found_error(
        self,
    ) -> None:
        service, uow = make_service()
        trip = await self._scheduled_trip_dto(service, uow)

        with self.assertRaises(NotFoundError):
            await service.change_trip_driver(
                ChangeTripDriverCommand(
                    trip_id=trip.id,
                    driver_id=NON_EXISTENT_DRIVER_ID,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_get_trip_by_id_returns_dto(self) -> None:
        service, uow = make_service()
        trip = await self._scheduled_trip_dto(service, uow)
        dto = await service.get_trip_by_id(
            GetTripByIdQuery(trip_id=trip.id), uow=uow
        )
        self.assertEqual(dto.id, trip.id)

    async def test_get_trip_by_id_with_nonexistent_id_raises_not_found_error(
        self,
    ) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.get_trip_by_id(
                GetTripByIdQuery(trip_id=NON_EXISTENT_TRIP_ID), uow=uow
            )

    async def test_list_trips_returns_summary_dtos(self) -> None:
        service, uow = make_service()
        await self._scheduled_trip_dto(service, uow)
        page = await service.list_trips(
            ListTripsQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(len(page.data), 1)
        self.assertIsInstance(page.data[0], TripSummaryDTO)


class TripApplicationServicePaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_trips_paginates_and_reports_total(self) -> None:
        service, uow = make_service()
        seed_driver_and_route(uow)
        for i in range(3):
            await service.schedule_trip(
                ScheduleTripCommand(
                    organization_id=VALID_ORG_ULID,
                    vehicle_id=f"01J8Z3K9G6X8YV5T4N2R7QW3V{i}",
                    driver_id=VALID_DRIVER_ULID,
                    route_id=VALID_ROUTE_ULID,
                    trip_type="morning",
                    scheduled_date=date(2026, 7, 20),
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await service.list_trips(
            ListTripsQuery(page_request=OffsetPageRequest(page=1, page_size=2)),
            uow=uow,
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(page.page, 1)
        self.assertEqual(page.page_size, 2)
        self.assertEqual(len(page.data), 2)

        second_page = await service.list_trips(
            ListTripsQuery(page_request=OffsetPageRequest(page=2, page_size=2)),
            uow=uow,
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_trips_filters_by_trip_type(self) -> None:
        service, uow = make_service()
        seed_driver_and_route(uow)
        await service.schedule_trip(
            ScheduleTripCommand(
                organization_id=VALID_ORG_ULID,
                vehicle_id="01J8Z3K9G6X8YV5T4N2R7QW3VM",
                driver_id=VALID_DRIVER_ULID,
                route_id=VALID_ROUTE_ULID,
                trip_type="morning",
                scheduled_date=date(2026, 7, 20),
                actor=make_actor(),
            ),
            uow=uow,
        )
        afternoon = await service.schedule_trip(
            ScheduleTripCommand(
                organization_id=VALID_ORG_ULID,
                vehicle_id="01J8Z3K9G6X8YV5T4N2R7QW3VA",
                driver_id=VALID_DRIVER_ULID,
                route_id=VALID_ROUTE_ULID,
                trip_type="afternoon",
                scheduled_date=date(2026, 7, 20),
                actor=make_actor(),
            ),
            uow=uow,
        )

        page = await service.list_trips(
            ListTripsQuery(
                page_request=OffsetPageRequest(),
                filters=[
                    FilterCondition(field="trip_type", op="eq", value="afternoon")
                ],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].id, afternoon.id)

    async def test_list_trips_sorts_descending_by_scheduled_date(self) -> None:
        service, uow = make_service()
        seed_driver_and_route(uow)
        for i, day in enumerate((18, 19, 20)):
            await service.schedule_trip(
                ScheduleTripCommand(
                    organization_id=VALID_ORG_ULID,
                    vehicle_id=f"01J8Z3K9G6X8YV5T4N2R7QW3W{i}",
                    driver_id=VALID_DRIVER_ULID,
                    route_id=VALID_ROUTE_ULID,
                    trip_type="morning",
                    scheduled_date=date(2026, 7, day),
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await service.list_trips(
            ListTripsQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="scheduled_date", descending=True)],
            ),
            uow=uow,
        )
        self.assertEqual(
            [dto.scheduled_date for dto in page.data],
            [date(2026, 7, 20), date(2026, 7, 19), date(2026, 7, 18)],
        )


if __name__ == "__main__":
    unittest.main()
