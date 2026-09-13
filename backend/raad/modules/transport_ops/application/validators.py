"""Application-layer command validators for `transport_ops` (Backend LLD §4.1's application
table: "Contextual pre-conditions of a use-case"). These check pre-conditions that need
repository I/O — exactly why they're an application concern and not a domain one, mirroring
`fleet_device.application.validators`'s identical reasoning and exact `ensure_*` naming.

**Phases 10.1-10.6: none were defined.** `Student`/`Parent` declare no uniqueness constraint
beyond their own primary key (`domain/repositories.py`'s own docstrings), no cross-aggregate
reference existed yet (no `route_id`/`parent_id`/`trip_id` on `Student`, no `Student` reference
on `Parent`), and existence-checking the very aggregate a use-case operates *on* lives on each
service itself (`StudentApplicationService._get_student_or_raise`, mirroring `Organization
ApplicationService._get_organization_or_raise` — not a function here). Tenant scoping needs no
manual check either way, being resolved once at the edge (`.claude/rules/backend.md` #4).

**Phase 10.7 addition — `StudentParent` is the first aggregate in this module needing this
file.** It references two *other* aggregates (`Student`, `Parent`) rather than checking its own
existence, exactly the shape `fleet_device.application.validators.ensure_vehicle_exists` already
establishes for a `vehicle_id` referenced by a `DeviceAssignment` command:

- `ensure_student_exists` / `ensure_parent_exists` → the in-context FKs `student_parents.
  student_id → students.id` / `student_parents.parent_id → parents.id` (Database Design §6.4).
- `ensure_link_not_duplicate` → the composite primary key `(student_id, parent_id)` — defense
  in depth over the DB-enforced constraint, surfacing a typed `ConflictError` instead of a raw
  `IntegrityError`, the same pattern `fleet_device.ensure_terminal_id_available` establishes.
- `ensure_link_exists` → backs `unlink_parent_from_student`, load-or-404 for a not-found
  relationship, mirroring `ensure_vehicle_exists`'s own shape.

Cross-organization rejection is **not** here — it needs no repository I/O once `Student`/
`Parent` are already loaded, so it lives in the domain layer instead
(`domain/entities.py`'s `StudentParent.link` docstring explains the split).

**Phase 10.8: none added for `Driver` either**, for the identical reason Phases 10.1-10.6 gave —
no uniqueness constraint beyond its own primary key, no cross-aggregate reference, and its own
existence-checking lives on `DriverApplicationService._get_driver_or_raise`
(`application/services.py`), not a function here.

**Phase 11 addition — `ensure_route_name_available`.** `routes` has a real per-tenant
uniqueness constraint this time (Database Design §6.5: `Unique (organization_id, name)`) —
mirroring `fleet_device.application.validators.ensure_plate_no_available`'s identical shape for
`vehicles`' own per-tenant `ux_vehicles__org_plate`. `Route`'s own existence-checking still
lives on `RouteApplicationService._get_route_or_raise`, not here, for the same reason
Phases 10.1-10.8 keep that check off this file.

**Phase 12 addition — `Trip` cross-aggregate checks.** `ensure_driver_exists`/
`ensure_route_exists` mirror `ensure_student_exists`/`ensure_parent_exists` exactly — `Trip`
references two *other* same-module aggregates (`Driver`, `Route`), the identical shape
`StudentParent` already establishes for `Student`/`Parent`. `ensure_vehicle_has_no_active_trip`
mirrors `fleet_device.application.validators.ensure_vehicle_has_no_active_device` exactly —
defense-in-depth over `ux_trips__active_vehicle` (the DB partial unique index,
`infra/models.py`), surfacing a typed `ConflictError` instead of a raw constraint violation, via
`TripRepository.active_trip_for_vehicle` (Backend LLD §7.2 verbatim). `Trip`'s own
existence-checking lives on `TripApplicationService._get_trip_or_raise`, not here, for the same
reason every other aggregate in this module keeps that check off this file.

**Phase 13 addition — `StudentAssignment` cross-aggregate checks.** `ensure_pickup_and_dropoff_
stops_exist` checks `Stop` existence via the already-loaded `Route`'s own `stops` collection —
`Stop` has no repository of its own to query directly (`domain/repositories.py`'s Phase 11
addition), the same "child entity, no independent existence check" situation
`fleet_device.application.validators` would face for a `Camera`. `ensure_student_has_no_active_
assignment` mirrors `ensure_vehicle_has_no_active_trip` exactly — defense-in-depth over
`ux_student_assignments__active_student` (the DB partial unique index, `infra/models.py`), via
`StudentAssignmentRepository.active_assignment_for_student`. `StudentAssignment`'s own
existence-checking lives on `StudentAssignmentApplicationService._get_assignment_or_raise`, not
here, for the same reason every other aggregate in this module keeps that check off this file.

**Finance UI cleanup addition (2026-09-12) — `ensure_family_vehicle_consistency`.** RAAD's own
family/vehicle business rule: every Student under the same Parent rides the same Vehicle (a
family never splits across buses — the Parent Invoice Vehicle filter reads *the family's* vehicle,
not an individual child's). Nothing previously enforced this — `StudentAssignment.assign()` took
whatever `vehicle_id` a caller supplied with no cross-sibling check at all. `vehicle_id` is set
exactly once, at `assign()` time, and never changed after (`domain/entities.py`'s own docstring),
so this is checked only there, the same "defense-in-depth over a business invariant, at the one
place it can ever be violated" shape every `ensure_*` function above already establishes. Needs
`student_parents` (to find the student's own parent(s), then that parent's *other* children) and
`student_assignments` (each sibling's own active vehicle) — both already same-module repositories
on this same `TransportOpsUnitOfWork`, so this is ordinary in-context I/O, not a cross-module read.
"""

from __future__ import annotations

from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Parent,
    Route,
    Student,
    StudentParent,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    ParentId,
    RouteId,
    StopId,
    StudentId,
    VehicleId,
)


async def ensure_student_exists(
    uow: TransportOpsUnitOfWork, student_id: StudentId
) -> Student:
    student = await uow.students.get(student_id)
    if student is None:
        raise NotFoundError(f"Student {student_id} not found.")
    return student


async def ensure_parent_exists(
    uow: TransportOpsUnitOfWork, parent_id: ParentId
) -> Parent:
    parent = await uow.parents.get(parent_id)
    if parent is None:
        raise NotFoundError(f"Parent {parent_id} not found.")
    return parent


async def ensure_link_not_duplicate(
    uow: TransportOpsUnitOfWork, student_id: StudentId, parent_id: ParentId
) -> None:
    existing = await uow.student_parents.get(student_id, parent_id)
    if existing is not None:
        raise ConflictError(
            f"Parent {parent_id} is already linked to student {student_id}."
        )


async def ensure_link_exists(
    uow: TransportOpsUnitOfWork, student_id: StudentId, parent_id: ParentId
) -> StudentParent:
    link = await uow.student_parents.get(student_id, parent_id)
    if link is None:
        raise NotFoundError(
            f"No link between student {student_id} and parent {parent_id}."
        )
    return link


async def ensure_route_name_available(uow: TransportOpsUnitOfWork, name: str) -> None:
    existing = await uow.routes.get_by_name(name)
    if existing is not None:
        raise ConflictError(
            f"A route named {name!r} already exists in this organization."
        )


async def ensure_driver_exists(
    uow: TransportOpsUnitOfWork, driver_id: DriverId
) -> Driver:
    driver = await uow.drivers.get(driver_id)
    if driver is None:
        raise NotFoundError(f"Driver {driver_id} not found.")
    return driver


async def ensure_route_exists(uow: TransportOpsUnitOfWork, route_id: RouteId) -> Route:
    route = await uow.routes.get(route_id)
    if route is None:
        raise NotFoundError(f"Route {route_id} not found.")
    return route


async def ensure_vehicle_has_no_active_trip(
    uow: TransportOpsUnitOfWork, vehicle_id: VehicleId
) -> None:
    active = await uow.trips.active_trip_for_vehicle(vehicle_id)
    if active is not None:
        raise ConflictError(
            f"Vehicle {vehicle_id} already has an active trip {active.id} "
            "(one active trip per vehicle, Database Design §6.8)."
        )


def ensure_pickup_and_dropoff_stops_exist(
    route: Route, pickup_stop_id: StopId, dropoff_stop_id: StopId
) -> None:
    """No repository query — `Stop` only exists as a member of an already-loaded `Route`'s
    `stops` collection (`domain/repositories.py`'s Phase 11 addition), so this is a pure,
    in-memory check over state the caller already has, not an I/O-dependent validator. Kept in
    this module for consistency with every other `ensure_*` pre-check, even though it takes no
    `uow`."""
    stop_ids = {stop.id for stop in route.stops}
    if pickup_stop_id not in stop_ids:
        raise NotFoundError(
            f"Stop {pickup_stop_id} not found on Route {route.id}."
        )
    if dropoff_stop_id not in stop_ids:
        raise NotFoundError(
            f"Stop {dropoff_stop_id} not found on Route {route.id}."
        )


async def ensure_student_has_no_active_assignment(
    uow: TransportOpsUnitOfWork, student_id: StudentId
) -> None:
    active = await uow.student_assignments.active_assignment_for_student(student_id)
    if active is not None:
        raise ConflictError(
            f"Student {student_id} already has an active assignment {active.id} "
            "(one active assignment per student, Database Design §6.7)."
        )


async def ensure_family_vehicle_consistency(
    uow: TransportOpsUnitOfWork, student_id: StudentId, vehicle_id: VehicleId | None
) -> None:
    """RAAD's family/vehicle business rule: one Parent/family = one Vehicle — every Student
    belonging to the same Parent must ride the same bus, never a different one each. `None` (no
    vehicle chosen yet for this assignment) never conflicts with anything — the rule is about a
    genuine mismatch between two *actual* vehicles, not about requiring one up front. A student
    with no linked parent yet has nothing to be consistent with, so this is a no-op for them too.

    Walks every parent linked to `student_id`, then every *other* student linked to that same
    parent (a sibling), and checks that sibling's own current active assignment (if any). A
    sibling with no active assignment, or an active assignment with no vehicle yet, never
    conflicts — only a sibling already riding a *different*, non-null vehicle does.

    **2026-09-12: demoted to a defense-in-depth safety net, not the primary enforcement.** The
    primary path is now `ParentApplicationService.register_parent_with_children`/`set_family_
    transportation` (`services.py`) — both assign one shared route/stops/vehicle to every one of
    a Parent's children at once, so a family can no longer be split across two buses by
    construction, not merely by a rejected second attempt. This check stays, unchanged, as the
    guard over the still-reachable single-student `assign_student_to_route` endpoint, so that
    path alone can never violate the same invariant."""
    if vehicle_id is None:
        return
    links = await uow.student_parents.list_by_student(student_id)
    for link in links:
        siblings = await uow.student_parents.list_by_parent(link.parent_id)
        for sibling_link in siblings:
            if sibling_link.student_id == student_id:
                continue
            sibling_assignment = await uow.student_assignments.active_assignment_for_student(
                sibling_link.student_id
            )
            if (
                sibling_assignment is not None
                and sibling_assignment.vehicle_id is not None
                and sibling_assignment.vehicle_id != vehicle_id
            ):
                raise ConflictError(
                    f"Cannot assign Student {student_id} to vehicle {vehicle_id}: sibling "
                    f"Student {sibling_link.student_id} (same Parent {link.parent_id}) is "
                    f"already assigned to vehicle {sibling_assignment.vehicle_id}. RAAD's "
                    "family/vehicle rule requires every child of the same Parent to ride the "
                    "same Vehicle."
                )
