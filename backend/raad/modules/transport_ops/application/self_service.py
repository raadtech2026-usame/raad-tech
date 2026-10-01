"""Mobile self-service for parents and drivers (ADR-0061).

Every method takes a `Principal` as its only identity input, the same structural rule
ADR-0023 set for `/me`: there is no parent, driver, staff or student id for a caller to
supply, so there is nothing to override. A caller with no matching `Parent`/`Driver` record
gets `NotFoundError` (404), never a 403 that would confirm what exists.

Reads are composed from this module's own repositories. The only data from elsewhere is the
bus's plate and label, asked for through `VehicleSummaryPort` (`.claude/rules/backend.md` #3).
Writes delegate to the services that already own the rule: unavailability to
`DailyOperationsApplicationService`, incidents to `IncidentApplicationService`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from raad.core.errors.exceptions import NotFoundError, RuleViolationError, ValidationError
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import RecordUnavailabilityCommand
from raad.modules.transport_ops.application.compliance import (
    compliance_to_dto,
    load_compliance_index,
)
from raad.modules.transport_ops.application.incident_services import (
    IncidentApplicationService,
    RecordIncidentCommand,
)
from raad.modules.transport_ops.application.operations_services import (
    DailyOperationsApplicationService,
)
from raad.modules.transport_ops.application.ports import (
    TransportOpsUnitOfWork,
    VehicleSummary,
    VehicleSummaryPort,
)
from raad.modules.transport_ops.application.queries import StaffComplianceDTO
from raad.modules.transport_ops.application.staff_services import DEFAULT_ALERT_LEAD_DAYS
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Incident,
    StaffUnavailability,
    Trip,
)
from raad.modules.transport_ops.domain.value_objects import (
    StaffAssignmentKind,
    StaffUnavailabilityId,
    TransportStaffId,
    TripId,
    UserId,
)

#: The longest window one call may ask for. A term is about three months.
MAX_TRIP_WINDOW_DAYS = 92
#: A driver reports days off; anything longer is a conversation with the office.
MAX_SELF_REPORTED_DAYS = 31


@dataclass(frozen=True)
class MyStopDTO:
    id: str
    name: str
    latitude: float
    longitude: float
    sequence_no: int


@dataclass(frozen=True)
class MyTripStudentDTO:
    student_id: str
    full_name: str


@dataclass(frozen=True)
class MyTripDTO:
    """One trip as its driver, or as a parent whose child rides it, sees it."""

    id: str
    trip_type: str
    status: str
    scheduled_date: date
    planned_departure: time | None
    started_at: datetime | None
    ended_at: datetime | None
    cancelled_reason: str | None
    route_id: str
    route_name: str | None
    vehicle: VehicleSummary | None
    #: Driver only: this trip normally belongs to another driver.
    is_cover: bool = False
    #: Parent only: which of the caller's own children ride it.
    students: list[MyTripStudentDTO] = field(default_factory=list)


@dataclass(frozen=True)
class MyCrewMemberDTO:
    full_name: str
    role_name: str | None
    is_me: bool
    is_substitute: bool


@dataclass(frozen=True)
class MyPassengerDTO:
    student_id: str
    full_name: str
    pickup_stop_name: str | None
    dropoff_stop_name: str | None


@dataclass(frozen=True)
class MyTripDetailDTO:
    trip: MyTripDTO
    stops: list[MyStopDTO]
    crew: list[MyCrewMemberDTO]
    passengers: list[MyPassengerDTO]


@dataclass(frozen=True)
class MyCrewDTO:
    vehicle: VehicleSummary
    members: list[MyCrewMemberDTO]


@dataclass(frozen=True)
class MyDocumentDTO:
    id: str
    type_name: str
    number: str | None
    issued_on: date | None
    expires_on: date | None
    status: str
    days_left: int | None


@dataclass(frozen=True)
class MyDocumentsDTO:
    documents: list[MyDocumentDTO]
    compliance: StaffComplianceDTO | None


@dataclass(frozen=True)
class MyUnavailabilityDTO:
    id: str
    starts_on: date
    ends_on: date
    reason: str
    note: str | None
    is_withdrawn: bool
    is_covered: bool


@dataclass(frozen=True)
class MyIncidentDTO:
    """What the reporter sees of their own report. The office's resolution, notes and the
    people it names stay Org Admin only (ADR-0056 §5)."""

    id: str
    category: str
    severity: str
    status: str
    occurred_at: datetime
    title: str
    description: str | None
    trip_id: str | None
    created_at: datetime
    closed_at: datetime | None


class SelfServiceApplicationService:
    def __init__(
        self,
        *,
        clock: Clock,
        vehicles: VehicleSummaryPort,
        operations: DailyOperationsApplicationService,
        incidents: IncidentApplicationService,
    ) -> None:
        self._clock = clock
        self._vehicles = vehicles
        self._operations = operations
        self._incidents = incidents

    def _today(self) -> date:
        return self._clock.now().date()

    # ---- identity -------------------------------------------------------------------------

    @staticmethod
    async def _driver(uow: TransportOpsUnitOfWork, principal: Principal) -> Driver:
        driver = (
            await uow.drivers.get_by_user_id(UserId(principal.user_id))
            if principal.role == Role.DRIVER
            else None
        )
        if driver is None:
            raise NotFoundError("No Driver profile is linked to this account.")
        return driver

    def _window(
        self, start: date | None, end: date | None, *, default_back: int, default_forward: int
    ) -> tuple[date, date]:
        today = self._today()
        start = start or today - timedelta(days=default_back)
        end = end or max(start, today + timedelta(days=default_forward))
        if end < start:
            raise ValidationError("'to' must not be before 'from'.")
        if (end - start).days > MAX_TRIP_WINDOW_DAYS:
            raise ValidationError(f"At most {MAX_TRIP_WINDOW_DAYS} days may be requested at once.")
        return start, end

    # ---- trips ----------------------------------------------------------------------------

    async def my_trips(
        self,
        principal: Principal,
        *,
        start: date | None = None,
        end: date | None = None,
        uow: TransportOpsUnitOfWork,
    ) -> list[MyTripDTO]:
        """A driver's own trips, or the trips a parent's children ride. Oldest first."""
        if principal.role == Role.DRIVER:
            start, end = self._window(start, end, default_back=0, default_forward=7)
            async with uow:
                driver = await self._driver(uow, principal)
                trips = [
                    t for t in await uow.trips.list_between(start, end) if t.driver_id == driver.id
                ]
                covers = await self._cover_trip_ids(uow, trips, driver)
                routes = await self._route_names(uow, trips)
            vehicles = await self._vehicle_summaries(trips, str(driver.organization_id))
            return [
                self._trip_dto(t, routes, vehicles, is_cover=str(t.id) in covers)
                for t in sorted(trips, key=_trip_order)
            ]
        if principal.role == Role.PARENT:
            start, end = self._window(start, end, default_back=30, default_forward=7)
            async with uow:
                parent = await uow.parents.get_by_user_id(UserId(principal.user_id))
                if parent is None:
                    raise NotFoundError("No Parent profile is linked to this account.")
                links = await uow.student_parents.list_by_parent(parent.id)
                students = await uow.students.list_by_ids([str(l.student_id) for l in links])
                riders: dict[str, list[MyTripStudentDTO]] = {}
                trips_by_id: dict[str, Trip] = {}
                for student in sorted(students, key=lambda s: s.full_name):
                    assignment = await uow.student_assignments.active_assignment_for_student(
                        student.id
                    )
                    if assignment is None or assignment.vehicle_id is None:
                        continue
                    # Before the child was assigned, that bus's trips were not the child's.
                    first_day = max(start, assignment.assigned_at.date())
                    if first_day > end:
                        continue
                    for trip in await uow.trips.list_between(
                        first_day, end, vehicle_id=assignment.vehicle_id
                    ):
                        if trip.route_id != assignment.route_id:
                            continue
                        trips_by_id[str(trip.id)] = trip
                        riders.setdefault(str(trip.id), []).append(
                            MyTripStudentDTO(str(student.id), student.full_name)
                        )
                trips = list(trips_by_id.values())
                routes = await self._route_names(uow, trips)
            vehicles = await self._vehicle_summaries(trips, str(parent.organization_id))
            return [
                self._trip_dto(t, routes, vehicles, students=riders[str(t.id)])
                for t in sorted(trips, key=_trip_order)
            ]
        raise NotFoundError("No Parent or Driver profile is linked to this account.")

    async def my_trip_detail(
        self, principal: Principal, trip_id: str, *, uow: TransportOpsUnitOfWork
    ) -> MyTripDetailDTO:
        """Driver only, own trip only: the stops, the crew that day and who rides."""
        async with uow:
            driver = await self._driver(uow, principal)
            trip = await uow.trips.get(TripId(trip_id))
            if trip is None or trip.driver_id != driver.id:
                raise NotFoundError(f"Trip {trip_id} not found.")
            route = await uow.routes.get(trip.route_id)
            stops = sorted(route.stops, key=lambda s: s.sequence_no) if route is not None else []
            stop_names = {str(s.id): s.name for s in stops}
            covers = await self._cover_trip_ids(uow, [trip], driver)
            crew = await self._crew_members(
                uow, trip.scheduled_date, [str(trip.vehicle_id)], str(driver.staff_id)
            )
            assignments = await uow.student_assignments.list_active_for_route_vehicle(
                trip.route_id, trip.vehicle_id
            )
            students = {
                str(s.id): s
                for s in await uow.students.list_by_ids([str(a.student_id) for a in assignments])
            }
            passengers = sorted(
                (
                    MyPassengerDTO(
                        student_id=str(a.student_id),
                        full_name=students[str(a.student_id)].full_name,
                        pickup_stop_name=stop_names.get(str(a.pickup_stop_id)),
                        dropoff_stop_name=stop_names.get(str(a.dropoff_stop_id)),
                    )
                    for a in assignments
                    if str(a.student_id) in students
                ),
                key=lambda p: p.full_name,
            )
            routes = {str(trip.route_id): route.name} if route is not None else {}
        vehicles = await self._vehicle_summaries([trip], str(driver.organization_id))
        return MyTripDetailDTO(
            trip=self._trip_dto(trip, routes, vehicles, is_cover=str(trip.id) in covers),
            stops=[
                MyStopDTO(str(s.id), s.name, s.latitude, s.longitude, s.sequence_no) for s in stops
            ],
            crew=crew.get(str(trip.vehicle_id), []),
            passengers=passengers,
        )

    # ---- crew -----------------------------------------------------------------------------

    async def my_crew(
        self, principal: Principal, *, day: date | None = None, uow: TransportOpsUnitOfWork
    ) -> list[MyCrewDTO]:
        """Who works on the driver's buses on `day`: the buses they drive a trip on, and the
        buses they are assigned to."""
        day = day or self._today()
        async with uow:
            driver = await self._driver(uow, principal)
            staff_id = str(driver.staff_id)
            vehicle_ids = {
                str(t.vehicle_id)
                for t in await uow.trips.list_between(day, day)
                if t.driver_id == driver.id
            }
            vehicle_ids |= {
                str(a.vehicle_id)
                for a in await uow.staff_assignments.list_between(day, day)
                if str(a.staff_id) == staff_id
            }
            crew = await self._crew_members(uow, day, sorted(vehicle_ids), staff_id)
        summaries = await self._vehicles.summaries(
            sorted(vehicle_ids), organization_id=str(driver.organization_id)
        )
        return [
            MyCrewDTO(vehicle=summaries[vehicle_id], members=crew.get(vehicle_id, []))
            for vehicle_id in sorted(vehicle_ids)
            if vehicle_id in summaries
        ]

    async def _crew_members(
        self, uow: TransportOpsUnitOfWork, day: date, vehicle_ids: list[str], my_staff_id: str
    ) -> dict[str, list[MyCrewMemberDTO]]:
        wanted = set(vehicle_ids)
        assignments = [
            a
            for a in await uow.staff_assignments.list_between(day, day)
            if str(a.vehicle_id) in wanted
        ]
        people = {
            str(s.id): s
            for s in await uow.staff.list_by_ids(sorted({str(a.staff_id) for a in assignments}))
        }
        role_names: dict[str, str] = {}
        for role_id in {a.role_id for a in assignments if a.role_id is not None}:
            role = await uow.staff_roles.get(role_id)
            if role is not None:
                role_names[str(role_id)] = role.name
        result: dict[str, list[MyCrewMemberDTO]] = {}
        for a in assignments:
            person = people.get(str(a.staff_id))
            if person is None:
                continue
            result.setdefault(str(a.vehicle_id), []).append(
                MyCrewMemberDTO(
                    full_name=person.full_name,
                    role_name=role_names.get(str(a.role_id)) if a.role_id else None,
                    is_me=str(a.staff_id) == my_staff_id,
                    is_substitute=a.kind is StaffAssignmentKind.TEMPORARY,
                )
            )
        for members in result.values():
            members.sort(key=lambda m: (not m.is_me, m.full_name))
        return result

    # ---- documents ------------------------------------------------------------------------

    async def my_documents(
        self, principal: Principal, *, uow: TransportOpsUnitOfWork
    ) -> MyDocumentsDTO:
        today = self._today()
        async with uow:
            driver = await self._driver(uow, principal)
            person = await uow.staff.get(driver.staff_id)
            if person is None:
                raise NotFoundError("No staff record is linked to this account.")
            documents = [
                d
                for d in await uow.staff_documents.list_for_staff(person.id)
                if d.replaced_by_id is None
            ]
            types = {
                str(t.id): t
                for t in await uow.staff_document_types.list_by_ids(
                    sorted({str(d.type_id) for d in documents})
                )
            }
            compliance = (await load_compliance_index(uow, [person])).of(person, today)
        items = []
        for d in documents:
            doc_type = types.get(str(d.type_id))
            lead = doc_type.alert_lead_days if doc_type else DEFAULT_ALERT_LEAD_DAYS
            items.append(
                MyDocumentDTO(
                    id=str(d.id),
                    type_name=doc_type.name if doc_type else "Document",
                    number=d.number,
                    issued_on=d.issued_on,
                    expires_on=d.expires_on,
                    status=d.status(today, lead).value,
                    days_left=d.days_left(today),
                )
            )
        items.sort(key=lambda i: (i.expires_on is None, i.expires_on or today, i.type_name))
        return MyDocumentsDTO(
            documents=items,
            compliance=compliance_to_dto(compliance) if compliance is not None else None,
        )

    # ---- unavailability -------------------------------------------------------------------

    async def my_unavailability(
        self, principal: Principal, *, uow: TransportOpsUnitOfWork
    ) -> list[MyUnavailabilityDTO]:
        async with uow:
            driver = await self._driver(uow, principal)
            items = await uow.unavailability.list_for_staff(driver.staff_id)
            return [await self._unavailability_dto(uow, item) for item in items]

    async def report_unavailability(
        self,
        principal: Principal,
        *,
        starts_on: date,
        ends_on: date,
        reason: str,
        note: str | None,
        uow: TransportOpsUnitOfWork,
    ) -> MyUnavailabilityDTO:
        """The driver states a fact about their own days (ADR-0053 §1: no request, no approval).
        Nothing is reassigned; the daily board and the uncovered-trip alerts show the gap."""
        if starts_on < self._today():
            raise ValidationError("An unavailability cannot start in the past.")
        if ends_on < starts_on:
            raise ValidationError("The last day must not be before the first day.")
        if (ends_on - starts_on).days >= MAX_SELF_REPORTED_DAYS:
            raise ValidationError(
                f"At most {MAX_SELF_REPORTED_DAYS} days can be reported from the app."
            )
        async with uow:
            driver = await self._driver(uow, principal)
            staff_id = driver.staff_id
            overlapping = await uow.unavailability.list_overlapping(
                starts_on, ends_on, staff_id=staff_id
            )
        if overlapping:
            raise RuleViolationError("These days overlap an unavailability already recorded.")
        created = await self._operations.record_unavailability(
            RecordUnavailabilityCommand(
                staff_id=str(staff_id),
                starts_on=starts_on,
                ends_on=ends_on,
                reason=reason,
                note=note,
                actor=principal,
            ),
            uow=uow,
        )
        return MyUnavailabilityDTO(
            id=created.id,
            starts_on=created.starts_on,
            ends_on=created.ends_on,
            reason=created.reason,
            note=created.note,
            is_withdrawn=False,
            is_covered=False,
        )

    async def withdraw_my_unavailability(
        self, principal: Principal, unavailability_id: str, *, uow: TransportOpsUnitOfWork
    ) -> None:
        """Only before the office has arranged cover: withdrawing would undo their work."""
        async with uow:
            driver = await self._driver(uow, principal)
            item = await uow.unavailability.get(StaffUnavailabilityId(unavailability_id))
            if item is None or item.staff_id != driver.staff_id:
                raise NotFoundError(f"Unavailability {unavailability_id} not found.")
            if item.withdrawn_at is not None:
                return
            if any(c.withdrawn_at is None for c in await uow.covers.list_for_unavailability(item.id)):
                raise RuleViolationError(
                    "A substitute has already been arranged. Contact the office to change this."
                )
        await self._operations.withdraw_unavailability(unavailability_id, actor=principal, uow=uow)

    @staticmethod
    async def _unavailability_dto(
        uow: TransportOpsUnitOfWork, item: StaffUnavailability
    ) -> MyUnavailabilityDTO:
        return MyUnavailabilityDTO(
            id=str(item.id),
            starts_on=item.starts_on,
            ends_on=item.ends_on,
            reason=item.reason.value,
            note=item.note,
            is_withdrawn=item.withdrawn_at is not None,
            is_covered=any(
                c.withdrawn_at is None for c in await uow.covers.list_for_unavailability(item.id)
            ),
        )

    # ---- incidents ------------------------------------------------------------------------

    async def my_incidents(
        self, principal: Principal, *, uow: TransportOpsUnitOfWork
    ) -> list[MyIncidentDTO]:
        async with uow:
            driver = await self._driver(uow, principal)
            incidents = await uow.incidents.list_reported_by(str(driver.staff_id))
            return [_incident_dto(i) for i in incidents]

    async def report_incident(
        self,
        principal: Principal,
        *,
        category: str,
        severity: str,
        occurred_at: datetime | None,
        title: str,
        description: str | None,
        trip_id: str | None,
        uow: TransportOpsUnitOfWork,
    ) -> MyIncidentDTO:
        """Records an incident in the office's log with the driver as its reporter. A trip may
        be named only if it is the driver's own; it supplies the bus and the route."""
        async with uow:
            driver = await self._driver(uow, principal)
            if trip_id is not None:
                trip = await uow.trips.get(TripId(trip_id))
                if trip is None or trip.driver_id != driver.id:
                    raise NotFoundError(f"Trip {trip_id} not found.")
            organization_id = str(driver.organization_id)
            staff_id = str(driver.staff_id)
        occurred_at = occurred_at or self._clock.now()
        if occurred_at.tzinfo is not None and occurred_at > self._clock.now() + timedelta(minutes=5):
            raise ValidationError("An incident cannot be in the future.")
        created = await self._incidents.record(
            RecordIncidentCommand(
                organization_id=organization_id,
                category=category,
                severity=severity,
                occurred_at=occurred_at,
                title=title,
                description=description,
                trip_id=trip_id,
                staff_ids=(staff_id,),
                reported_by_staff_id=staff_id,
                actor=principal,
            ),
            uow=uow,
        )
        return MyIncidentDTO(
            id=created.id,
            category=created.category,
            severity=created.severity,
            status=created.status,
            occurred_at=created.occurred_at,
            title=created.title,
            description=created.description,
            trip_id=created.trip_id,
            created_at=created.created_at,
            closed_at=created.closed_at,
        )

    # ---- notification recipients (used by `notifications`' subscribers) --------------------

    async def driver_user_id_for_trip(
        self, trip_id: str, *, uow: TransportOpsUnitOfWork
    ) -> tuple[Trip | None, str | None]:
        """The trip and its driver's login, for telling a driver their trip was cancelled."""
        async with uow:
            trip = await uow.trips.get(TripId(trip_id))
            if trip is None:
                return None, None
            driver = await uow.drivers.get(trip.driver_id)
            return trip, (str(driver.user_id) if driver is not None else None)

    async def user_id_for_staff(self, staff_id: str, *, uow: TransportOpsUnitOfWork) -> str | None:
        """The login of a staff member who has driver access, else `None` (only drivers log in)."""
        async with uow:
            driver = await uow.drivers.get_by_staff_id(TransportStaffId(staff_id))
            return str(driver.user_id) if driver is not None else None

    # ---- helpers --------------------------------------------------------------------------

    @staticmethod
    async def _route_names(uow: TransportOpsUnitOfWork, trips: list[Trip]) -> dict[str, str]:
        names: dict[str, str] = {}
        for route_id in {t.route_id for t in trips}:
            route = await uow.routes.get(route_id)
            if route is not None:
                names[str(route_id)] = route.name
        return names

    @staticmethod
    async def _cover_trip_ids(
        uow: TransportOpsUnitOfWork, trips: list[Trip], driver: Driver
    ) -> set[str]:
        """Trips whose timetable names another driver: the caller is standing in."""
        entries: dict[str, object] = {}
        covering: set[str] = set()
        for trip in trips:
            if trip.timetable_entry_id is None:
                continue
            key = str(trip.timetable_entry_id)
            if key not in entries:
                entries[key] = await uow.timetable.get(trip.timetable_entry_id)
            entry = entries[key]
            if entry is not None and entry.default_driver_id != driver.id:  # type: ignore[attr-defined]
                covering.add(str(trip.id))
        return covering

    async def _vehicle_summaries(
        self, trips: list[Trip], organization_id: str
    ) -> dict[str, VehicleSummary]:
        ids = sorted({str(t.vehicle_id) for t in trips})
        return await self._vehicles.summaries(ids, organization_id=organization_id) if ids else {}

    @staticmethod
    def _trip_dto(
        trip: Trip,
        routes: dict[str, str],
        vehicles: dict[str, VehicleSummary],
        *,
        is_cover: bool = False,
        students: list[MyTripStudentDTO] | None = None,
    ) -> MyTripDTO:
        return MyTripDTO(
            id=str(trip.id),
            trip_type=trip.trip_type.value,
            status=trip.status.value,
            scheduled_date=trip.scheduled_date,
            planned_departure=trip.planned_departure,
            started_at=trip.started_at,
            ended_at=trip.ended_at,
            cancelled_reason=trip.cancelled_reason,
            route_id=str(trip.route_id),
            route_name=routes.get(str(trip.route_id)),
            vehicle=vehicles.get(str(trip.vehicle_id)),
            is_cover=is_cover,
            students=students or [],
        )


def _trip_order(trip: Trip) -> tuple:
    return (
        trip.scheduled_date,
        0 if trip.trip_type.value == "morning" else 1,
        trip.planned_departure or time.min,
        str(trip.id),
    )


def _incident_dto(incident: Incident) -> MyIncidentDTO:
    return MyIncidentDTO(
        id=str(incident.id),
        category=incident.category.value,
        severity=incident.severity.value,
        status=incident.status.value,
        occurred_at=incident.occurred_at,
        title=incident.title,
        description=incident.description,
        trip_id=str(incident.trip_id) if incident.trip_id else None,
        created_at=incident.created_at,
        closed_at=incident.closed_at,
    )


__all__ = [
    "MAX_SELF_REPORTED_DAYS",
    "MAX_TRIP_WINDOW_DAYS",
    "MyCrewDTO",
    "MyCrewMemberDTO",
    "MyDocumentDTO",
    "MyDocumentsDTO",
    "MyIncidentDTO",
    "MyPassengerDTO",
    "MyStopDTO",
    "MyTripDTO",
    "MyTripDetailDTO",
    "MyTripStudentDTO",
    "MyUnavailabilityDTO",
    "SelfServiceApplicationService",
]
