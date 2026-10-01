"""Daily transport operations (ADR-0052, ADR-0053, ADR-0054): the weekly timetable, closed days,
trip generation, staff unavailability, cover, coverage and the daily board.

Three rules live here rather than in one aggregate, because each spans several:

* **One coverage rule** (`_Coverage`): the board, the generation plan and the alert job all ask
  the same object whether a trip is covered. Two copies of that rule would disagree.
* **One generation plan** (`_plan_generation`): the scheduled job, the manual action and its
  preview all run it, so what the preview promises is what gets created.
* **Cover changes crew and trips together**: a driver's cover switches that driver's scheduled
  trips in the same commit that creates the substitute's temporary crew assignment.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta

from raad.core.errors.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    CreateCoverCommand,
    GenerateTripsCommand,
    RecordClosureCommand,
    RecordUnavailabilityCommand,
    SaveTimetableEntryCommand,
)
from raad.modules.transport_ops.application.ports import (
    TransportOpsUnitOfWork,
    VehicleDirectoryPort,
)
from raad.modules.transport_ops.application.queries import (
    BoardCrewDTO,
    BoardTripDTO,
    BoardVehicleDTO,
    ClosureDTO,
    CoverDTO,
    DailyBoardDTO,
    GenerationResultDTO,
    PlannedTripDTO,
    SkippedTripDTO,
    TimetableEntryDTO,
    UncoveredTripAlertDTO,
    UnavailabilityDTO,
)
from raad.modules.transport_ops.application.compliance import (
    ComplianceIndex,
    load_compliance_index,
    planning_compliance_warnings,
)
from raad.modules.transport_ops.application.services import _enforce_own_organization
from raad.modules.transport_ops.domain.entities import (
    Driver,
    OperatingClosure,
    RouteTimetableEntry,
    StaffCover,
    StaffUnavailability,
    TransportStaff,
    Trip,
    VehicleStaffAssignment,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    OperatingClosureId,
    OrganizationId,
    RouteId,
    RouteStatus,
    RouteTimetableEntryId,
    StaffAssignmentKind,
    StaffCoverId,
    StaffUnavailabilityId,
    TransportStaffId,
    TransportStaffRoleId,
    TransportStaffStatus,
    TripId,
    TripStatus,
    TripType,
    UnavailabilityReason,
    VehicleId,
    VehicleStaffAssignmentId,
)

MAX_GENERATION_DAYS = 31

#: Trips still able to run; only these can be uncovered.
_OPEN_STATUSES = (TripStatus.SCHEDULED, TripStatus.IN_PROGRESS, TripStatus.INTERRUPTED)


@dataclass
class _Coverage:
    """Everything needed to answer "is this trip covered?" for a date range, loaded once."""

    drivers: dict[str, Driver]
    staff: dict[str, TransportStaff]
    unavailability: list[StaffUnavailability]
    covers: list[StaffCover]
    #: ADR-0059 §1. `None` only where documents are not loaded; then nothing is flagged for them.
    compliance: ComplianceIndex | None = None

    def unavailable(self, staff_id: TransportStaffId, day: date) -> StaffUnavailability | None:
        return next(
            (u for u in self.unavailability if u.staff_id == staff_id and u.covers(day)), None
        )

    def cover_for(
        self, absent_staff_id: TransportStaffId, vehicle_id: VehicleId, day: date
    ) -> StaffCover | None:
        return next(
            (
                c
                for c in self.covers
                if c.absent_staff_id == absent_staff_id
                and c.vehicle_id == vehicle_id
                and c.covers(day)
            ),
            None,
        )

    def driver_problem(self, driver_id: DriverId, day: date) -> str | None:
        """ADR-0053 §3: why this driver cannot drive on `day`, or `None`."""
        driver = self.drivers.get(str(driver_id))
        if driver is None or driver.status is not DriverStatus.ACTIVE:
            return "driver_inactive"
        person = self.staff.get(str(driver.staff_id))
        if person is None or person.status is not TransportStaffStatus.ACTIVE:
            return "driver_not_active"
        if self.unavailable(driver.staff_id, day) is not None:
            return "driver_unavailable"
        if self.compliance is not None:
            compliance = self.compliance.of(person, day)
            if compliance is not None and not compliance.is_compliant:
                return "driver_not_compliant"
        return None

    def crew_compliance_status(self, staff_id: TransportStaffId | str, day: date) -> str | None:
        person = self.staff.get(str(staff_id))
        if person is None or self.compliance is None:
            return None
        compliance = self.compliance.of(person, day)
        return compliance.status.value if compliance is not None else None

    def trip_problem(self, trip: Trip) -> str | None:
        if trip.status not in _OPEN_STATUSES:
            return None
        return self.driver_problem(trip.driver_id, trip.scheduled_date)

    def driver_name(self, driver_id: DriverId | str) -> str | None:
        driver = self.drivers.get(str(driver_id))
        person = self.staff.get(str(driver.staff_id)) if driver else None
        return person.full_name if person else None


def _alert_key(trip: Trip, reason: str) -> str:
    return f"{reason}:{trip.driver_id}"


class DailyOperationsApplicationService:
    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        vehicle_directory: VehicleDirectoryPort,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._vehicle_directory = vehicle_directory

    def _today(self) -> date:
        return self._clock.now().date()

    # ---- timetable ----------------------------------------------------------------------------

    async def list_timetable(
        self, *, uow: TransportOpsUnitOfWork, route_id: str | None = None
    ) -> list[TimetableEntryDTO]:
        async with uow:
            entries = await uow.timetable.list_all(route_id=RouteId(route_id) if route_id else None)
            return await self._timetable_dtos(uow, entries)

    async def save_timetable_entry(
        self, command: SaveTimetableEntryCommand, *, uow: TransportOpsUnitOfWork
    ) -> TimetableEntryDTO:
        _enforce_own_organization(actor=command.actor, organization_id=command.organization_id)
        try:
            trip_type = TripType(command.trip_type)
        except ValueError as exc:
            raise ValidationError(f"Unknown trip type {command.trip_type!r}.") from exc
        async with uow:
            organization_id = command.organization_id
            route = await uow.routes.get(RouteId(command.route_id))
            if route is None or str(route.organization_id) != organization_id:
                raise NotFoundError(f"Route {command.route_id} not found.")
            driver = await uow.drivers.get(DriverId(command.default_driver_id))
            if driver is None or str(driver.organization_id) != organization_id:
                raise NotFoundError(f"Driver {command.default_driver_id} not found.")
            if await self._vehicle_directory.organization_of_vehicle(command.vehicle_id) != organization_id:
                raise NotFoundError(f"Vehicle {command.vehicle_id} not found.")
            # ADR-0059 §3: refused only when the driver is being set or changed.
            current = (
                await uow.timetable.get(RouteTimetableEntryId(command.entry_id))
                if command.entry_id is not None
                else None
            )
            warnings = await planning_compliance_warnings(
                uow,
                driver.staff_id,
                max(self._today(), command.valid_from),
                refuse_blocked=current is None or current.default_driver_id != driver.id,
            )
            values = dict(
                route_id=route.id,
                vehicle_id=VehicleId(command.vehicle_id),
                trip_type=trip_type,
                weekdays=tuple(command.weekdays),
                planned_departure=command.planned_departure,
                default_driver_id=driver.id,
                valid_from=command.valid_from,
                valid_until=command.valid_until,
                is_active=command.is_active,
            )
            if command.entry_id is None:
                entry = RouteTimetableEntry.create(
                    id=RouteTimetableEntryId(self._id_generator.new_id()),
                    organization_id=OrganizationId(organization_id),
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                    **values,
                )
                uow.timetable.add(entry)
            else:
                entry = await uow.timetable.get(RouteTimetableEntryId(command.entry_id))
                if entry is None or str(entry.organization_id) != organization_id:
                    raise NotFoundError(f"Timetable entry {command.entry_id} not found.")
                entry.update(clock=self._clock, actor_id=command.actor.user_id, **values)
            for other in await uow.timetable.list_all():
                if entry.clashes_with(other):
                    raise ConflictError(
                        "This bus already has a timetable entry for that period on one of those "
                        "weekdays."
                    )
            uow.record_events(entry.pull_domain_events())
            await uow.commit()
            return replace((await self._timetable_dtos(uow, [entry]))[0], warnings=warnings)

    # ---- closures -----------------------------------------------------------------------------

    async def list_closures(
        self, *, uow: TransportOpsUnitOfWork, start: date, end: date
    ) -> list[ClosureDTO]:
        async with uow:
            return [self._closure_dto(c) for c in await uow.closures.list_overlapping(start, end)]

    async def record_closure(
        self, command: RecordClosureCommand, *, uow: TransportOpsUnitOfWork
    ) -> ClosureDTO:
        _enforce_own_organization(actor=command.actor, organization_id=command.organization_id)
        async with uow:
            closure = OperatingClosure.record(
                id=OperatingClosureId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                starts_on=command.starts_on,
                ends_on=command.ends_on,
                label=command.label,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.closures.add(closure)
            uow.record_events(closure.pull_domain_events())
            await uow.commit()
            return self._closure_dto(closure)

    async def withdraw_closure(
        self, closure_id: str, *, actor: Principal, uow: TransportOpsUnitOfWork
    ) -> ClosureDTO:
        async with uow:
            closure = await uow.closures.get(OperatingClosureId(closure_id))
            if closure is None:
                raise NotFoundError(f"Closure {closure_id} not found.")
            closure.withdraw(clock=self._clock, actor_id=actor.user_id)
            uow.record_events(closure.pull_domain_events())
            await uow.commit()
            return self._closure_dto(closure)

    # ---- unavailability and cover ---------------------------------------------------------------

    async def record_unavailability(
        self, command: RecordUnavailabilityCommand, *, uow: TransportOpsUnitOfWork
    ) -> UnavailabilityDTO:
        try:
            reason = UnavailabilityReason(command.reason)
        except ValueError as exc:
            raise ValidationError(f"Unknown reason {command.reason!r}.") from exc
        async with uow:
            person = await uow.staff.get(TransportStaffId(command.staff_id))
            if person is None:
                raise NotFoundError(f"Staff member {command.staff_id} not found.")
            item = StaffUnavailability.record(
                id=StaffUnavailabilityId(self._id_generator.new_id()),
                organization_id=person.organization_id,
                staff_id=person.id,
                starts_on=command.starts_on,
                ends_on=command.ends_on,
                reason=reason,
                note=(command.note or "").strip() or None,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.unavailability.add(item)
            uow.record_events(item.pull_domain_events())
            await uow.commit()
            return (await self._unavailability_dtos(uow, [item]))[0]

    async def withdraw_unavailability(
        self, unavailability_id: str, *, actor: Principal, uow: TransportOpsUnitOfWork
    ) -> UnavailabilityDTO:
        """Withdraws its covers too (ADR-0053 §2), restoring the original driver where it can."""
        async with uow:
            item = await uow.unavailability.get(StaffUnavailabilityId(unavailability_id))
            if item is None:
                raise NotFoundError(f"Unavailability {unavailability_id} not found.")
            for cover in await uow.covers.list_for_unavailability(item.id):
                await self._withdraw_cover(uow, cover, actor=actor, absent_available=True)
            item.withdraw(clock=self._clock, actor_id=actor.user_id)
            uow.record_events(item.pull_domain_events())
            await uow.commit()
            return (await self._unavailability_dtos(uow, [item]))[0]

    async def list_unavailability(
        self,
        *,
        uow: TransportOpsUnitOfWork,
        staff_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[UnavailabilityDTO]:
        async with uow:
            if staff_id is not None:
                items = await uow.unavailability.list_for_staff(TransportStaffId(staff_id))
            else:
                start = start or self._today()
                items = await uow.unavailability.list_overlapping(start, end or start + timedelta(days=30))
            return await self._unavailability_dtos(uow, items)

    async def create_cover(
        self, command: CreateCoverCommand, *, uow: TransportOpsUnitOfWork
    ) -> CoverDTO:
        async with uow:
            item = await uow.unavailability.get(StaffUnavailabilityId(command.unavailability_id))
            if item is None:
                raise NotFoundError(f"Unavailability {command.unavailability_id} not found.")
            organization_id = str(item.organization_id)
            substitute = await uow.staff.get(TransportStaffId(command.substitute_staff_id))
            if substitute is None or str(substitute.organization_id) != organization_id:
                raise NotFoundError(f"Staff member {command.substitute_staff_id} not found.")
            if substitute.status is not TransportStaffStatus.ACTIVE:
                raise DomainError(f"{substitute.full_name} is not active and cannot cover.")
            if await self._vehicle_directory.organization_of_vehicle(command.vehicle_id) != organization_id:
                raise NotFoundError(f"Vehicle {command.vehicle_id} not found.")
            vehicle_id = VehicleId(command.vehicle_id)
            starts_on = command.starts_on or item.starts_on
            ends_on = command.ends_on or item.ends_on
            absent = await uow.staff.get(item.staff_id)
            absent_driver = await uow.drivers.get_by_staff_id(item.staff_id)
            substitute_driver = await uow.drivers.get_by_staff_id(substitute.id)
            warnings: list[str] = []
            if absent_driver is not None and (
                substitute_driver is None or substitute_driver.status is not DriverStatus.ACTIVE
            ):
                raise DomainError(
                    f"{substitute.full_name} has no active driver access and cannot cover a driver."
                )
            if absent is not None and absent.role_id != substitute.role_id:
                warnings.append("The substitute's job title differs from the absent person's.")
            if await uow.unavailability.list_overlapping(starts_on, ends_on, staff_id=substitute.id):
                raise DomainError(f"{substitute.full_name} is also unavailable during that period.")
            # ADR-0059 §3: every day of the cover; the last day finds a lapse on any of them.
            warnings.extend(
                await planning_compliance_warnings(uow, substitute.id, ends_on, refuse_blocked=True)
            )
            # Every read happens before the first new row is added. A query issued after an
            # `add()` autoflushes, and autoflush orders INSERTs by class name, not by foreign
            # key: `staff_covers` would be written before the crew row it references.
            trips_to_switch: list[Trip] = []
            if absent_driver is not None and substitute_driver is not None:
                trips_to_switch = [
                    trip
                    for trip in await uow.trips.list_between(
                        max(starts_on, self._today()), ends_on, vehicle_id=vehicle_id
                    )
                    if trip.status is TripStatus.SCHEDULED and trip.driver_id == absent_driver.id
                ]

            # The substitute's crew row (ADR-0050). Someone already on this bus for the whole
            # period needs no new row.
            existing = await uow.staff_assignments.list_for(staff_id=substitute.id, vehicle_id=vehicle_id)
            assignment: VehicleStaffAssignment | None = None
            if not any(
                a.starts_on <= starts_on and (a.ends_on is None or a.ends_on >= ends_on)
                for a in existing
            ):
                if any(a.overlaps(starts_on, ends_on) for a in existing):
                    raise ConflictError(
                        f"{substitute.full_name} is already on this bus for part of that period."
                    )
                absent_role = next(
                    (
                        a.role_id
                        for a in await uow.staff_assignments.list_for(staff_id=item.staff_id, vehicle_id=vehicle_id)
                        if a.is_current(starts_on)
                    ),
                    None,
                )
                assignment = VehicleStaffAssignment.assign(
                    id=VehicleStaffAssignmentId(self._id_generator.new_id()),
                    organization_id=item.organization_id,
                    staff_id=substitute.id,
                    vehicle_id=vehicle_id,
                    role_id=absent_role or substitute.role_id,
                    route_id=None,
                    starts_on=starts_on,
                    ends_on=ends_on,
                    kind=StaffAssignmentKind.TEMPORARY,
                    reason=f"Covering for {absent.full_name if absent else 'a colleague'}"[:255],
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                uow.staff_assignments.add(assignment)
                uow.record_events(assignment.pull_domain_events())

            cover = StaffCover.create(
                id=StaffCoverId(self._id_generator.new_id()),
                organization_id=item.organization_id,
                unavailability=item,
                substitute_staff_id=substitute.id,
                vehicle_id=vehicle_id,
                starts_on=starts_on,
                ends_on=ends_on,
                assignment_id=assignment.id if assignment else None,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.covers.add(cover)
            uow.record_events(cover.pull_domain_events())

            for trip in trips_to_switch:
                trip.change_driver(
                    substitute_driver.id,  # type: ignore[union-attr]
                    new_driver_organization_id=substitute_driver.organization_id,  # type: ignore[union-attr]
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                uow.record_events(trip.pull_domain_events())
            reassigned = len(trips_to_switch)
            await uow.commit()
            dto = (await self._cover_dtos(uow, [cover]))[0]
            return replace(dto, trips_reassigned=reassigned, warnings=warnings)

    async def withdraw_cover(
        self, cover_id: str, *, actor: Principal, uow: TransportOpsUnitOfWork
    ) -> CoverDTO:
        async with uow:
            cover = await uow.covers.get(StaffCoverId(cover_id))
            if cover is None:
                raise NotFoundError(f"Cover {cover_id} not found.")
            await self._withdraw_cover(uow, cover, actor=actor, absent_available=False)
            await uow.commit()
            return (await self._cover_dtos(uow, [cover]))[0]

    async def _withdraw_cover(
        self,
        uow: TransportOpsUnitOfWork,
        cover: StaffCover,
        *,
        actor: Principal,
        absent_available: bool,
    ) -> None:
        """Ends the substitute's crew row and hands scheduled trips back to the original driver
        on days they are available. `absent_available` is set when the unavailability itself is
        being withdrawn, so its own days no longer count against the original driver."""
        if not cover.withdraw(clock=self._clock, actor_id=actor.user_id):
            return
        uow.record_events(cover.pull_domain_events())
        today = self._today()
        if cover.assignment_id is not None:
            assignment = await uow.staff_assignments.get(cover.assignment_id)
            if assignment is not None and assignment.end(today, clock=self._clock, actor_id=actor.user_id):
                uow.record_events(assignment.pull_domain_events())
        absent_driver = await uow.drivers.get_by_staff_id(cover.absent_staff_id)
        substitute_driver = await uow.drivers.get_by_staff_id(cover.substitute_staff_id)
        if absent_driver is None or substitute_driver is None:
            return
        start = max(cover.starts_on, today)
        if start > cover.ends_on:
            return
        others = [
            u
            for u in await uow.unavailability.list_overlapping(start, cover.ends_on, staff_id=cover.absent_staff_id)
            if not (absent_available and u.id == cover.unavailability_id)
        ]
        for trip in await uow.trips.list_between(start, cover.ends_on, vehicle_id=cover.vehicle_id):
            if trip.status is not TripStatus.SCHEDULED or trip.driver_id != substitute_driver.id:
                continue
            if any(u.covers(trip.scheduled_date) for u in others):
                continue
            trip.change_driver(
                absent_driver.id,
                new_driver_organization_id=absent_driver.organization_id,
                clock=self._clock,
                actor_id=actor.user_id,
            )
            uow.record_events(trip.pull_domain_events())

    # ---- coverage and the daily board -----------------------------------------------------------

    async def _load_coverage(self, uow: TransportOpsUnitOfWork, trips: list[Trip], start: date, end: date) -> _Coverage:
        drivers = {str(d.id): d for d in await uow.drivers.list_by_ids([str(t.driver_id) for t in trips])}
        staff = {str(s.id): s for s in await uow.staff.list_by_ids([str(d.staff_id) for d in drivers.values()])}
        return _Coverage(
            drivers=drivers,
            staff=staff,
            unavailability=await uow.unavailability.list_overlapping(start, end),
            covers=await uow.covers.list_overlapping(start, end),
            compliance=await load_compliance_index(uow, list(staff.values())),
        )

    async def daily_board(self, day: date, *, uow: TransportOpsUnitOfWork) -> DailyBoardDTO:
        async with uow:
            trips = await uow.trips.list_between(day, day)
            coverage = await self._load_coverage(uow, trips, day, day)
            crew_rows = [a for a in await uow.staff_assignments.list_between(day, day) if a.is_current(day)]
            crew_staff = {
                str(s.id): s for s in await uow.staff.list_by_ids([str(a.staff_id) for a in crew_rows])
            }
            coverage.staff.update(crew_staff)
            routes = {}
            for route_id in {str(t.route_id) for t in trips}:
                route = await uow.routes.get(RouteId(route_id))
                if route is not None:
                    routes[route_id] = route.name
            role_names = {}
            for role_id in {str(a.role_id) for a in crew_rows if a.role_id}:
                role = await uow.staff_roles.get(TransportStaffRoleId(role_id))
                if role is not None:
                    role_names[role_id] = role.name
            substitute_ids = {str(c.substitute_staff_id) for c in coverage.covers if c.covers(day)}
            coverage.staff.update(
                {str(s.id): s for s in await uow.staff.list_by_ids(sorted(substitute_ids))}
            )
            closures = [c.label for c in await uow.closures.list_overlapping(day, day)]
            # Reloaded now that crew and substitutes are known: the board badges them too.
            coverage.compliance = await load_compliance_index(uow, list(coverage.staff.values()))

            by_vehicle: dict[str, dict] = defaultdict(lambda: {"trips": [], "crew": []})
            uncovered = 0
            for trip in trips:
                problem = coverage.trip_problem(trip)
                uncovered += problem is not None
                by_vehicle[str(trip.vehicle_id)]["trips"].append(
                    BoardTripDTO(
                        id=str(trip.id),
                        trip_type=trip.trip_type.value,
                        route_id=str(trip.route_id),
                        route_name=routes.get(str(trip.route_id)),
                        planned_departure=trip.planned_departure,
                        driver_id=str(trip.driver_id),
                        driver_name=coverage.driver_name(trip.driver_id),
                        status=trip.status.value,
                        cancelled_reason=trip.cancelled_reason,
                        uncovered_reason=problem,
                    )
                )
            gaps: dict[str, int] = defaultdict(int)
            for a in crew_rows:
                person = crew_staff.get(str(a.staff_id))
                away = coverage.unavailable(a.staff_id, day)
                cover = coverage.cover_for(a.staff_id, a.vehicle_id, day) if away else None
                substitute = coverage.staff.get(str(cover.substitute_staff_id)) if cover else None
                covered_by = substitute.full_name if substitute else None
                if away is not None and cover is None:
                    gaps[str(a.vehicle_id)] += 1
                by_vehicle[str(a.vehicle_id)]["crew"].append(
                    BoardCrewDTO(
                        staff_id=str(a.staff_id),
                        staff_name=person.full_name if person else str(a.staff_id),
                        role_name=role_names.get(str(a.role_id)) if a.role_id else None,
                        is_substitute=str(a.staff_id) in substitute_ids and a.kind is StaffAssignmentKind.TEMPORARY,
                        is_unavailable=away is not None,
                        covered_by=covered_by,
                        compliance_status=coverage.crew_compliance_status(a.staff_id, day),
                    )
                )
            vehicles = [
                BoardVehicleDTO(
                    vehicle_id=vehicle_id,
                    trips=sorted(v["trips"], key=lambda t: t.trip_type),
                    crew=sorted(v["crew"], key=lambda c: c.staff_name),
                    crew_gaps=gaps.get(vehicle_id, 0),
                )
                for vehicle_id, v in sorted(by_vehicle.items())
            ]
            return DailyBoardDTO(date=day, closures=closures, vehicles=vehicles, uncovered_trips=uncovered)

    # ---- generation (ADR-0052 §4) ---------------------------------------------------------------

    async def generate_trips(
        self, command: GenerateTripsCommand, *, uow: TransportOpsUnitOfWork
    ) -> GenerationResultDTO:
        if not 1 <= command.days <= MAX_GENERATION_DAYS:
            raise ValidationError(f"days must be between 1 and {MAX_GENERATION_DAYS}.")
        start = command.start or self._today()
        end = start + timedelta(days=command.days - 1)
        async with uow:
            plan, skipped, closed_days, entries_by_id, drivers = await self._plan_generation(uow, start, end)
            created = 0
            if not command.dry_run:
                for planned in plan:
                    entry = entries_by_id[planned.timetable_entry_id]
                    driver = drivers[planned.driver_id]
                    trip = Trip.schedule(
                        id=TripId(self._id_generator.new_id()),
                        organization_id=entry.organization_id,
                        vehicle_id=entry.vehicle_id,
                        driver_id=driver.id,
                        driver_organization_id=driver.organization_id,
                        route_id=entry.route_id,
                        route_organization_id=entry.organization_id,
                        trip_type=entry.trip_type,
                        scheduled_date=planned.scheduled_date,
                        clock=self._clock,
                        actor_id=command.actor.user_id,
                        timetable_entry_id=entry.id,
                        planned_departure=entry.planned_departure,
                    )
                    uow.trips.add(trip)
                    uow.record_events(trip.pull_domain_events())
                    created += 1
                if created:
                    await uow.commit()
            return GenerationResultDTO(
                start=start,
                days=command.days,
                dry_run=command.dry_run,
                to_create=plan,
                skipped=skipped,
                closed_days=closed_days,
                created=created,
            )

    async def _plan_generation(self, uow: TransportOpsUnitOfWork, start: date, end: date):
        entries = [e for e in await uow.timetable.list_all() if e.is_active]
        entries_by_id = {str(e.id): e for e in entries}
        existing = {
            (str(t.vehicle_id), t.scheduled_date, t.trip_type.value)
            for t in await uow.trips.list_between(start, end)
        }
        closures = await uow.closures.list_overlapping(start, end)
        default_drivers = {
            str(d.id): d
            for d in await uow.drivers.list_by_ids([str(e.default_driver_id) for e in entries])
        }
        coverage = _Coverage(
            drivers=dict(default_drivers),
            staff={
                str(s.id): s
                for s in await uow.staff.list_by_ids([str(d.staff_id) for d in default_drivers.values()])
            },
            unavailability=await uow.unavailability.list_overlapping(start, end),
            covers=await uow.covers.list_overlapping(start, end),
        )
        substitute_staff = [str(c.substitute_staff_id) for c in coverage.covers]
        substitutes = {
            str(d.staff_id): d for d in await uow.drivers.list_by_staff_ids(substitute_staff)
        }
        drivers = dict(default_drivers)
        drivers.update({str(d.id): d for d in substitutes.values()})
        coverage.drivers = drivers
        coverage.staff.update({str(s.id): s for s in await uow.staff.list_by_ids(substitute_staff)})
        coverage.compliance = await load_compliance_index(uow, list(coverage.staff.values()))

        plan: list[PlannedTripDTO] = []
        skipped: list[SkippedTripDTO] = []
        closed_days: set[date] = set()
        vehicle_orgs: dict[str, str | None] = {}
        route_ok: dict[str, bool] = {}
        for entry in entries:
            entry_id = str(entry.id)
            vehicle = str(entry.vehicle_id)
            if vehicle not in vehicle_orgs:
                vehicle_orgs[vehicle] = await self._vehicle_directory.organization_of_vehicle(vehicle)
            if vehicle_orgs[vehicle] != str(entry.organization_id):
                skipped.append(SkippedTripDTO(entry_id, None, "bus_not_in_organization"))
                continue
            if str(entry.route_id) not in route_ok:
                route = await uow.routes.get(entry.route_id)
                route_ok[str(entry.route_id)] = route is not None and route.status is RouteStatus.ACTIVE
            if not route_ok[str(entry.route_id)]:
                skipped.append(SkippedTripDTO(entry_id, None, "route_inactive"))
                continue
            default = default_drivers.get(str(entry.default_driver_id))
            if default is None or default.status is not DriverStatus.ACTIVE:
                skipped.append(SkippedTripDTO(entry_id, None, "default_driver_inactive"))
                continue
            day = start
            while day <= end:
                if entry.runs_on(day):
                    if any(c.covers(day) and c.organization_id == entry.organization_id for c in closures):
                        closed_days.add(day)
                    elif (vehicle, day, entry.trip_type.value) not in existing:
                        driver_id, is_substitute = default.id, False
                        if coverage.unavailable(default.staff_id, day) is not None:
                            cover = coverage.cover_for(default.staff_id, entry.vehicle_id, day)
                            sub = substitutes.get(str(cover.substitute_staff_id)) if cover else None
                            if sub is not None and sub.status is DriverStatus.ACTIVE:
                                driver_id, is_substitute = sub.id, True
                        plan.append(
                            PlannedTripDTO(
                                timetable_entry_id=entry_id,
                                scheduled_date=day,
                                trip_type=entry.trip_type.value,
                                route_id=str(entry.route_id),
                                vehicle_id=vehicle,
                                driver_id=str(driver_id),
                                is_substitute=is_substitute,
                                uncovered_reason=coverage.driver_problem(driver_id, day),
                            )
                        )
                        existing.add((vehicle, day, entry.trip_type.value))
                day += timedelta(days=1)
        return plan, skipped, sorted(closed_days), entries_by_id, drivers

    # ---- alerts (ADR-0053 §5) -------------------------------------------------------------------

    async def collect_uncovered_alerts(
        self, *, uow: TransportOpsUnitOfWork, days: int = 2
    ) -> list[UncoveredTripAlertDTO]:
        """Uncovered trips from today whose cause has not been announced yet. A trip that is
        covered again has its key cleared here, so a later recurrence is announced afresh."""
        today = self._today()
        end = today + timedelta(days=days - 1)
        async with uow:
            trips = await uow.trips.list_between(today, end)
            coverage = await self._load_coverage(uow, trips, today, end)
            alerts: list[UncoveredTripAlertDTO] = []
            cleared = False
            route_names: dict[str, str | None] = {}
            for trip in trips:
                problem = coverage.trip_problem(trip)
                if problem is None:
                    if trip.coverage_alert_key is not None:
                        trip.mark_coverage_alerted(None)
                        cleared = True
                    continue
                key = _alert_key(trip, problem)
                if key == trip.coverage_alert_key:
                    continue
                if str(trip.route_id) not in route_names:
                    route = await uow.routes.get(trip.route_id)
                    route_names[str(trip.route_id)] = route.name if route else None
                alerts.append(
                    UncoveredTripAlertDTO(
                        organization_id=str(trip.organization_id),
                        trip_id=str(trip.id),
                        scheduled_date=trip.scheduled_date,
                        trip_type=trip.trip_type.value,
                        vehicle_id=str(trip.vehicle_id),
                        route_name=route_names[str(trip.route_id)],
                        driver_name=coverage.driver_name(trip.driver_id),
                        reason=problem,
                        key=key,
                    )
                )
            if cleared:
                await uow.commit()
            return alerts

    async def mark_uncovered_alerted(
        self, trip_id: str, key: str, *, uow: TransportOpsUnitOfWork
    ) -> None:
        async with uow:
            trip = await uow.trips.get(TripId(trip_id))
            if trip is None:
                return
            trip.mark_coverage_alerted(key)
            await uow.commit()

    async def uncovered_today(self, *, uow: TransportOpsUnitOfWork) -> dict[str, int]:
        """Organization id → number of uncovered trips today (the morning summary)."""
        today = self._today()
        async with uow:
            trips = await uow.trips.list_between(today, today)
            coverage = await self._load_coverage(uow, trips, today, today)
            counts: dict[str, int] = defaultdict(int)
            for trip in trips:
                if coverage.trip_problem(trip) is not None:
                    counts[str(trip.organization_id)] += 1
            return dict(counts)

    # ---- cancellation recipients (ADR-0054 §2) ----------------------------------------------------

    async def parent_user_ids_for_trip(
        self, trip_id: str, *, uow: TransportOpsUnitOfWork
    ) -> tuple[Trip | None, list[str]]:
        """The trip and the logins of parents whose children ride its route on its bus."""
        async with uow:
            trip = await uow.trips.get(TripId(trip_id))
            if trip is None:
                return None, []
            assignments = await uow.student_assignments.list_active_for_route_vehicle(
                trip.route_id, trip.vehicle_id
            )
            links = await uow.student_parents.list_by_students([a.student_id for a in assignments])
            parents = await uow.parents.list_by_ids([str(link.parent_id) for link in links])
            return trip, sorted({str(p.user_id) for p in parents if p.user_id})

    # ---- DTO helpers ----------------------------------------------------------------------------

    @staticmethod
    def _closure_dto(closure: OperatingClosure) -> ClosureDTO:
        return ClosureDTO(
            id=str(closure.id),
            organization_id=str(closure.organization_id),
            starts_on=closure.starts_on,
            ends_on=closure.ends_on,
            label=closure.label,
            withdrawn_at=closure.withdrawn_at,
        )

    async def _timetable_dtos(
        self, uow: TransportOpsUnitOfWork, entries: list[RouteTimetableEntry]
    ) -> list[TimetableEntryDTO]:
        drivers = {str(d.id): d for d in await uow.drivers.list_by_ids([str(e.default_driver_id) for e in entries])}
        staff = {str(s.id): s for s in await uow.staff.list_by_ids([str(d.staff_id) for d in drivers.values()])}
        routes: dict[str, str | None] = {}
        for entry in entries:
            if str(entry.route_id) not in routes:
                route = await uow.routes.get(entry.route_id)
                routes[str(entry.route_id)] = route.name if route else None
        result = []
        for e in entries:
            driver = drivers.get(str(e.default_driver_id))
            person = staff.get(str(driver.staff_id)) if driver else None
            result.append(
                TimetableEntryDTO(
                    id=str(e.id),
                    organization_id=str(e.organization_id),
                    route_id=str(e.route_id),
                    route_name=routes.get(str(e.route_id)),
                    vehicle_id=str(e.vehicle_id),
                    trip_type=e.trip_type.value,
                    weekdays=list(e.weekdays),
                    planned_departure=e.planned_departure,
                    default_driver_id=str(e.default_driver_id),
                    default_driver_name=person.full_name if person else None,
                    valid_from=e.valid_from,
                    valid_until=e.valid_until,
                    is_active=e.is_active,
                )
            )
        return result

    async def _cover_dtos(self, uow: TransportOpsUnitOfWork, covers: list[StaffCover]) -> list[CoverDTO]:
        ids = [str(c.absent_staff_id) for c in covers] + [str(c.substitute_staff_id) for c in covers]
        names = {str(s.id): s.full_name for s in await uow.staff.list_by_ids(ids)}
        return [
            CoverDTO(
                id=str(c.id),
                unavailability_id=str(c.unavailability_id),
                absent_staff_id=str(c.absent_staff_id),
                absent_staff_name=names.get(str(c.absent_staff_id), str(c.absent_staff_id)),
                substitute_staff_id=str(c.substitute_staff_id),
                substitute_staff_name=names.get(str(c.substitute_staff_id), str(c.substitute_staff_id)),
                vehicle_id=str(c.vehicle_id),
                starts_on=c.starts_on,
                ends_on=c.ends_on,
                withdrawn_at=c.withdrawn_at,
            )
            for c in covers
        ]

    async def _unavailability_dtos(
        self, uow: TransportOpsUnitOfWork, items: list[StaffUnavailability]
    ) -> list[UnavailabilityDTO]:
        names = {str(s.id): s.full_name for s in await uow.staff.list_by_ids([str(i.staff_id) for i in items])}
        result = []
        for item in items:
            covers = await self._cover_dtos(uow, await uow.covers.list_for_unavailability(item.id))
            result.append(
                UnavailabilityDTO(
                    id=str(item.id),
                    organization_id=str(item.organization_id),
                    staff_id=str(item.staff_id),
                    staff_name=names.get(str(item.staff_id), str(item.staff_id)),
                    starts_on=item.starts_on,
                    ends_on=item.ends_on,
                    reason=item.reason.value,
                    note=item.note,
                    withdrawn_at=item.withdrawn_at,
                    covers=covers,
                )
            )
        return result
