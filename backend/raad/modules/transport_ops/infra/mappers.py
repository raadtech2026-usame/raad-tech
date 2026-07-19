"""ORM ↔ Domain mappers for `transport_ops` (Backend LLD §7.1 "aggregate-in/aggregate-out";
§17 `db`). Mappers own **every** conversion between SQLAlchemy rows and domain objects —
repositories (`repositories.py`) never construct or read ORM columns directly outside calling
these functions, and never return an ORM model to a caller. Mirrors
`organization.infra.mappers`'s `existing=` in-place-update pattern exactly.

**Phase 10.7 addition: `student_parent_to_model`/`model_to_student_parent`.** `StudentParent`
has no surrogate id — `existing=` still works the same way (the caller supplies the already-
tracked `StudentParentModel` instance, keyed by the composite `(student_id, parent_id)` in
`repositories.py`, rather than by a single `id`), but a brand-new instance's constructor takes
`student_id`/`parent_id` instead of `id=...`.

**Phase 10.8 addition: `driver_to_model`/`model_to_driver`.** Mirrors `parent_to_model`/
`model_to_parent`'s exact `existing=` in-place-update pattern.

**Phase 11 addition: `route_to_model`/`model_to_route` (+ `stop_to_model`/`model_to_stop`).**
The `Route` aggregate owns `Stop` children (Phase 11), so `route_to_model` also syncs the stop
collection — mirroring `fleet_device.infra.mappers.device_to_model`'s camera-sync exactly for
the add/update halves, but going one step further: unlike `Camera` (no removal domain
behavior, so `device_to_model` never deletes a row), `Route.remove_stop` *does* exist
(`domain/entities.py`), so `route_to_model` also removes any tracked `StopModel` row whose id
is no longer present among `route.stops` — `RouteModel.stops`'s `cascade="all, delete-orphan"`
(`infra/models.py`) then deletes that orphaned row on flush.

**Phase 12 addition: `trip_to_model`/`model_to_trip`.** Mirrors `driver_to_model`/
`model_to_driver`'s exact `existing=` in-place-update pattern — `Trip` has no child-entity
collection to sync (unlike `Route`), so the mapper is a flat field projection. `_to_naive_utc`
strips tzinfo off `started_at`/`ended_at` before they reach the ORM row — see its own
docstring for the live-verification finding that motivated it.

**Phase 13 addition: `student_assignment_to_model`/`model_to_student_assignment`.** Mirrors
`trip_to_model`/`model_to_trip`'s exact shape, including reusing `_to_naive_utc` for
`assigned_at`/`ended_at` — both come from the same `Clock.now()` source as `Trip.started_at`/
`ended_at`, so the identical tz-aware-into-naive-column mismatch applies pre-emptively here
rather than being rediscovered live again.
"""

from __future__ import annotations

from datetime import datetime

from raad.modules.transport_ops.domain.entities import (
    Driver,
    Parent,
    Route,
    Stop,
    Student,
    StudentAssignment,
    StudentParent,
    Trip,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
    RouteId,
    RouteStatus,
    StopId,
    StudentAssignmentId,
    StudentAssignmentStatus,
    StudentId,
    StudentStatus,
    TripId,
    TripStatus,
    TripType,
    UserId,
    VehicleId,
)
from raad.modules.transport_ops.infra.models import (
    DriverModel,
    ParentModel,
    RouteModel,
    StopModel,
    StudentAssignmentModel,
    StudentModel,
    StudentParentModel,
    TripModel,
)


def student_to_model(
    student: Student, *, existing: StudentModel | None = None
) -> StudentModel:
    """Projects a `Student` aggregate onto its ORM row. If `existing` is given, mutates and
    returns that same instance (so the SQLAlchemy session keeps tracking the one row it already
    knows about, rather than a duplicate) — otherwise constructs a new `StudentModel`.
    """
    model = existing if existing is not None else StudentModel(id=str(student.id))
    model.organization_id = str(student.organization_id)
    model.full_name = student.full_name
    model.external_ref = student.external_ref
    model.status = student.status.value
    return model


def model_to_student(model: StudentModel) -> Student:
    return Student(
        id=StudentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        full_name=model.full_name,
        external_ref=model.external_ref,
        status=StudentStatus(model.status),
    )


def parent_to_model(
    parent: Parent, *, existing: ParentModel | None = None
) -> ParentModel:
    """Projects a `Parent` aggregate onto its ORM row, mirroring `student_to_model`'s exact
    `existing=` in-place-update pattern."""
    model = existing if existing is not None else ParentModel(id=str(parent.id))
    model.organization_id = str(parent.organization_id)
    model.user_id = str(parent.user_id)
    model.full_name = parent.full_name
    model.phone = str(parent.phone) if parent.phone is not None else None
    model.status = parent.status.value
    return model


def model_to_parent(model: ParentModel) -> Parent:
    return Parent(
        id=ParentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        user_id=UserId(model.user_id),
        full_name=model.full_name,
        phone=PhoneNumber(model.phone) if model.phone else None,
        status=ParentStatus(model.status),
    )


def student_parent_to_model(
    link: StudentParent, *, existing: StudentParentModel | None = None
) -> StudentParentModel:
    """Projects a `StudentParent` aggregate onto its ORM row, mirroring `student_to_model`'s
    `existing=` in-place-update pattern — see module docstring for the one difference (no
    `id=...` constructor argument)."""
    model = (
        existing
        if existing is not None
        else StudentParentModel(
            student_id=str(link.student_id), parent_id=str(link.parent_id)
        )
    )
    model.relationship = link.relationship
    model.is_primary = link.is_primary
    return model


def model_to_student_parent(model: StudentParentModel) -> StudentParent:
    return StudentParent(
        student_id=StudentId(model.student_id),
        parent_id=ParentId(model.parent_id),
        relationship=model.relationship,
        is_primary=model.is_primary,
    )


def driver_to_model(
    driver: Driver, *, existing: DriverModel | None = None
) -> DriverModel:
    """Projects a `Driver` aggregate onto its ORM row, mirroring `parent_to_model`'s exact
    `existing=` in-place-update pattern."""
    model = existing if existing is not None else DriverModel(id=str(driver.id))
    model.organization_id = str(driver.organization_id)
    model.user_id = str(driver.user_id)
    model.license_no = driver.license_no
    model.status = driver.status.value
    return model


def model_to_driver(model: DriverModel) -> Driver:
    return Driver(
        id=DriverId(model.id),
        organization_id=OrganizationId(model.organization_id),
        user_id=UserId(model.user_id),
        license_no=model.license_no,
        status=DriverStatus(model.status),
    )


def stop_to_model(
    stop: Stop,
    *,
    route_id: str,
    organization_id: str,
    existing: StopModel | None = None,
) -> StopModel:
    model = existing if existing is not None else StopModel(id=str(stop.id))
    model.organization_id = organization_id
    model.route_id = route_id
    model.name = stop.name
    model.latitude = stop.latitude
    model.longitude = stop.longitude
    model.sequence_no = stop.sequence_no
    model.geofence_radius_m = stop.geofence_radius_m
    return model


def model_to_stop(model: StopModel) -> Stop:
    return Stop(
        id=StopId(model.id),
        name=model.name,
        latitude=model.latitude,
        longitude=model.longitude,
        sequence_no=model.sequence_no,
        geofence_radius_m=model.geofence_radius_m,
    )


def route_to_model(route: Route, *, existing: RouteModel | None = None) -> RouteModel:
    """Projects a `Route` aggregate (including its stops) onto its ORM row — see module
    docstring for the add/update/**remove** stop-collection sync rules."""
    model = existing if existing is not None else RouteModel(id=str(route.id))
    model.organization_id = str(route.organization_id)
    model.name = route.name
    model.status = route.status.value

    existing_rows = {row.id: row for row in model.stops}
    current_ids = {str(stop.id) for stop in route.stops}
    for row_id, row in list(existing_rows.items()):
        if row_id not in current_ids:
            model.stops.remove(
                row
            )  # cascade="all, delete-orphan" deletes the orphaned row

    for stop in route.stops:
        row = existing_rows.get(str(stop.id))
        if row is not None:
            stop_to_model(
                stop,
                route_id=str(route.id),
                organization_id=str(route.organization_id),
                existing=row,
            )
        else:
            model.stops.append(
                stop_to_model(
                    stop,
                    route_id=str(route.id),
                    organization_id=str(route.organization_id),
                )
            )
    return model


def model_to_route(model: RouteModel) -> Route:
    return Route(
        id=RouteId(model.id),
        organization_id=OrganizationId(model.organization_id),
        name=model.name,
        status=RouteStatus(model.status),
        stops=[model_to_stop(row) for row in model.stops],
    )


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """`started_at`/`ended_at` come from `Clock.now()` (`SystemClock` returns tz-aware UTC,
    `domain/entities.py`'s `Trip.start`/`end`) but `TripModel.started_at`/`ended_at` are
    `DateTime(timezone=False)` (Database Design §1's naive-storage convention, `core/db/
    mixins.py`'s `utcnow()`) — found live: asyncpg's codec for `TIMESTAMP WITHOUT TIME ZONE`
    rejects a tz-aware `datetime` outright (`DataError: can't subtract offset-naive and
    offset-aware datetimes`), caught by this module's own integration tests. Strips tzinfo
    here, at the ORM-translation boundary, rather than in the domain layer, which stores
    whatever the injected `Clock` returns."""
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def trip_to_model(trip: Trip, *, existing: TripModel | None = None) -> TripModel:
    """Projects a `Trip` aggregate onto its ORM row, mirroring `driver_to_model`'s exact
    `existing=` in-place-update pattern."""
    model = existing if existing is not None else TripModel(id=str(trip.id))
    model.organization_id = str(trip.organization_id)
    model.vehicle_id = str(trip.vehicle_id)
    model.driver_id = str(trip.driver_id)
    model.route_id = str(trip.route_id)
    model.trip_type = trip.trip_type.value
    model.status = trip.status.value
    model.scheduled_date = trip.scheduled_date
    model.started_at = _to_naive_utc(trip.started_at)
    model.ended_at = _to_naive_utc(trip.ended_at)
    return model


def model_to_trip(model: TripModel) -> Trip:
    return Trip(
        id=TripId(model.id),
        organization_id=OrganizationId(model.organization_id),
        vehicle_id=VehicleId(model.vehicle_id),
        driver_id=DriverId(model.driver_id),
        route_id=RouteId(model.route_id),
        trip_type=TripType(model.trip_type),
        status=TripStatus(model.status),
        scheduled_date=model.scheduled_date,
        started_at=model.started_at,
        ended_at=model.ended_at,
    )


def student_assignment_to_model(
    assignment: StudentAssignment, *, existing: StudentAssignmentModel | None = None
) -> StudentAssignmentModel:
    """Projects a `StudentAssignment` aggregate onto its ORM row, mirroring `trip_to_model`'s
    exact `existing=` in-place-update pattern, including `_to_naive_utc` for `assigned_at`/
    `ended_at`."""
    model = (
        existing
        if existing is not None
        else StudentAssignmentModel(id=str(assignment.id))
    )
    model.organization_id = str(assignment.organization_id)
    model.student_id = str(assignment.student_id)
    model.route_id = str(assignment.route_id)
    model.pickup_stop_id = str(assignment.pickup_stop_id)
    model.dropoff_stop_id = str(assignment.dropoff_stop_id)
    model.vehicle_id = (
        str(assignment.vehicle_id) if assignment.vehicle_id is not None else None
    )
    model.status = assignment.status.value
    model.assigned_at = _to_naive_utc(assignment.assigned_at)
    model.ended_at = _to_naive_utc(assignment.ended_at)
    return model


def model_to_student_assignment(model: StudentAssignmentModel) -> StudentAssignment:
    return StudentAssignment(
        id=StudentAssignmentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        student_id=StudentId(model.student_id),
        route_id=RouteId(model.route_id),
        pickup_stop_id=StopId(model.pickup_stop_id),
        dropoff_stop_id=StopId(model.dropoff_stop_id),
        vehicle_id=VehicleId(model.vehicle_id) if model.vehicle_id else None,
        status=StudentAssignmentStatus(model.status),
        assigned_at=model.assigned_at,
        ended_at=model.ended_at,
    )
