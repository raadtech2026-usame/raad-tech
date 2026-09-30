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
    OperatingClosure,
    RouteTimetableEntry,
    StaffCover,
    StaffDocument,
    StaffDocumentType,
    StaffUnavailability,
    Stop,
    Student,
    StudentAssignment,
    StudentParent,
    TransportStaff,
    TransportStaffRole,
    Trip,
    VehicleStaffAssignment,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    Gender,
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
    RouteId,
    RouteStatus,
    OperatingClosureId,
    RouteTimetableEntryId,
    StaffAssignmentKind,
    StaffCoverId,
    StaffDocumentId,
    StaffDocumentTypeId,
    StaffUnavailabilityId,
    StopId,
    StudentAssignmentId,
    StudentAssignmentStatus,
    StudentId,
    StudentStatus,
    TripId,
    TripStatus,
    TransportStaffId,
    TransportStaffRoleId,
    TransportStaffStatus,
    TripType,
    UnavailabilityReason,
    UserId,
    VehicleId,
    VehicleStaffAssignmentId,
)
from raad.modules.transport_ops.infra.models import (
    DriverModel,
    ParentModel,
    RouteModel,
    StopModel,
    StudentAssignmentModel,
    StudentModel,
    OperatingClosureModel,
    RouteTimetableEntryModel,
    StaffCoverModel,
    StaffDocumentModel,
    StaffDocumentTypeModel,
    StaffUnavailabilityModel,
    StudentParentModel,
    TransportStaffModel,
    TransportStaffRoleModel,
    TripModel,
    VehicleStaffAssignmentModel,
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
    model.created_at = _to_naive_utc(student.created_at)
    model.updated_at = _to_naive_utc(student.updated_at)
    model.date_of_birth = student.date_of_birth
    model.gender = student.gender.value if student.gender is not None else None
    model.notes = student.notes
    return model


def model_to_student(model: StudentModel) -> Student:
    return Student(
        id=StudentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        full_name=model.full_name,
        external_ref=model.external_ref,
        status=StudentStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
        date_of_birth=model.date_of_birth,
        gender=Gender(model.gender) if model.gender else None,
        notes=model.notes,
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
    model.has_video_live_access = parent.has_video_live_access
    model.has_video_playback_access = parent.has_video_playback_access
    model.created_at = _to_naive_utc(parent.created_at)
    model.updated_at = _to_naive_utc(parent.updated_at)
    model.alternate_phone = (
        str(parent.alternate_phone) if parent.alternate_phone is not None else None
    )
    model.address = parent.address
    model.emergency_contact_name = parent.emergency_contact_name
    model.emergency_contact_phone = (
        str(parent.emergency_contact_phone)
        if parent.emergency_contact_phone is not None
        else None
    )
    model.notes = parent.notes
    return model


def model_to_parent(model: ParentModel) -> Parent:
    return Parent(
        id=ParentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        user_id=UserId(model.user_id),
        full_name=model.full_name,
        phone=PhoneNumber(model.phone) if model.phone else None,
        status=ParentStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
        has_video_live_access=model.has_video_live_access,
        has_video_playback_access=model.has_video_playback_access,
        alternate_phone=PhoneNumber(model.alternate_phone) if model.alternate_phone else None,
        address=model.address,
        emergency_contact_name=model.emergency_contact_name,
        emergency_contact_phone=(
            PhoneNumber(model.emergency_contact_phone)
            if model.emergency_contact_phone
            else None
        ),
        notes=model.notes,
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
    model.staff_id = str(driver.staff_id)
    model.created_at = _to_naive_utc(driver.created_at)
    model.updated_at = _to_naive_utc(driver.updated_at)
    return model


def model_to_driver(model: DriverModel) -> Driver:
    return Driver(
        id=DriverId(model.id),
        organization_id=OrganizationId(model.organization_id),
        user_id=UserId(model.user_id),
        license_no=model.license_no,
        status=DriverStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
        staff_id=TransportStaffId(model.staff_id),
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
    model.created_at = _to_naive_utc(route.created_at)
    model.updated_at = _to_naive_utc(route.updated_at)

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
        created_at=model.created_at,
        updated_at=model.updated_at,
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
    model.created_at = _to_naive_utc(trip.created_at)
    model.updated_at = _to_naive_utc(trip.updated_at)
    model.timetable_entry_id = _str_or_none(trip.timetable_entry_id)
    model.planned_departure = trip.planned_departure
    model.cancelled_at = _to_naive_utc(trip.cancelled_at)
    model.cancelled_reason = trip.cancelled_reason
    model.coverage_alert_key = trip.coverage_alert_key
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
        created_at=model.created_at,
        updated_at=model.updated_at,
        timetable_entry_id=(
            RouteTimetableEntryId(model.timetable_entry_id.strip())
            if model.timetable_entry_id
            else None
        ),
        planned_departure=model.planned_departure,
        cancelled_at=model.cancelled_at,
        cancelled_reason=model.cancelled_reason,
        coverage_alert_key=model.coverage_alert_key,
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
    model.created_at = _to_naive_utc(assignment.created_at)
    model.updated_at = _to_naive_utc(assignment.updated_at)
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
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# ---- ADR-0049/0050/0051 --------------------------------------------------------------------------


def _phone(value: str | None) -> PhoneNumber | None:
    return PhoneNumber(value) if value else None


def _str_or_none(value: object | None) -> str | None:
    return str(value) if value is not None else None


def transport_staff_role_to_model(
    role: TransportStaffRole, *, existing: TransportStaffRoleModel | None = None
) -> TransportStaffRoleModel:
    model = existing if existing is not None else TransportStaffRoleModel(id=str(role.id))
    model.organization_id = str(role.organization_id)
    model.name = role.name
    model.sort_order = role.sort_order
    model.is_archived = role.is_archived
    model.created_at = _to_naive_utc(role.created_at)
    model.updated_at = _to_naive_utc(role.updated_at)
    return model


def model_to_transport_staff_role(model: TransportStaffRoleModel) -> TransportStaffRole:
    return TransportStaffRole(
        id=TransportStaffRoleId(model.id),
        organization_id=OrganizationId(model.organization_id),
        name=model.name,
        sort_order=model.sort_order,
        is_archived=model.is_archived,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def transport_staff_to_model(
    staff: TransportStaff, *, existing: TransportStaffModel | None = None
) -> TransportStaffModel:
    model = existing if existing is not None else TransportStaffModel(id=str(staff.id))
    model.organization_id = str(staff.organization_id)
    model.full_name = staff.full_name
    model.phone = _str_or_none(staff.phone)
    model.alternate_phone = _str_or_none(staff.alternate_phone)
    model.role_id = _str_or_none(staff.role_id)
    model.employee_ref = staff.employee_ref
    model.start_date = staff.start_date
    model.status = staff.status.value
    model.emergency_contact_name = staff.emergency_contact_name
    model.emergency_contact_phone = _str_or_none(staff.emergency_contact_phone)
    model.notes = staff.notes
    model.left_on = staff.left_on
    model.created_at = _to_naive_utc(staff.created_at)
    model.updated_at = _to_naive_utc(staff.updated_at)
    return model


def model_to_transport_staff(model: TransportStaffModel) -> TransportStaff:
    return TransportStaff(
        id=TransportStaffId(model.id),
        organization_id=OrganizationId(model.organization_id),
        full_name=model.full_name,
        phone=_phone(model.phone),
        alternate_phone=_phone(model.alternate_phone),
        role_id=TransportStaffRoleId(model.role_id) if model.role_id else None,
        employee_ref=model.employee_ref,
        start_date=model.start_date,
        status=TransportStaffStatus(model.status),
        emergency_contact_name=model.emergency_contact_name,
        emergency_contact_phone=_phone(model.emergency_contact_phone),
        notes=model.notes,
        left_on=model.left_on,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def vehicle_staff_assignment_to_model(
    assignment: VehicleStaffAssignment,
    *,
    existing: VehicleStaffAssignmentModel | None = None,
) -> VehicleStaffAssignmentModel:
    model = (
        existing
        if existing is not None
        else VehicleStaffAssignmentModel(id=str(assignment.id))
    )
    model.organization_id = str(assignment.organization_id)
    model.staff_id = str(assignment.staff_id)
    model.vehicle_id = str(assignment.vehicle_id)
    model.role_id = _str_or_none(assignment.role_id)
    model.route_id = _str_or_none(assignment.route_id)
    model.starts_on = assignment.starts_on
    model.ends_on = assignment.ends_on
    model.kind = assignment.kind.value
    model.reason = assignment.reason
    model.created_at = _to_naive_utc(assignment.created_at)
    model.updated_at = _to_naive_utc(assignment.updated_at)
    return model


def model_to_vehicle_staff_assignment(
    model: VehicleStaffAssignmentModel,
) -> VehicleStaffAssignment:
    return VehicleStaffAssignment(
        id=VehicleStaffAssignmentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        staff_id=TransportStaffId(model.staff_id),
        vehicle_id=VehicleId(model.vehicle_id),
        role_id=TransportStaffRoleId(model.role_id) if model.role_id else None,
        route_id=RouteId(model.route_id) if model.route_id else None,
        starts_on=model.starts_on,
        ends_on=model.ends_on,
        kind=StaffAssignmentKind(model.kind),
        reason=model.reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def staff_document_type_to_model(
    doc_type: StaffDocumentType, *, existing: StaffDocumentTypeModel | None = None
) -> StaffDocumentTypeModel:
    model = existing if existing is not None else StaffDocumentTypeModel(id=str(doc_type.id))
    model.organization_id = str(doc_type.organization_id)
    model.name = doc_type.name
    model.alert_lead_days = list(doc_type.alert_lead_days)
    model.is_archived = doc_type.is_archived
    model.created_at = _to_naive_utc(doc_type.created_at)
    model.updated_at = _to_naive_utc(doc_type.updated_at)
    return model


def model_to_staff_document_type(model: StaffDocumentTypeModel) -> StaffDocumentType:
    return StaffDocumentType(
        id=StaffDocumentTypeId(model.id),
        organization_id=OrganizationId(model.organization_id),
        name=model.name,
        alert_lead_days=tuple(model.alert_lead_days or ()),
        is_archived=model.is_archived,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def staff_document_to_model(
    document: StaffDocument, *, existing: StaffDocumentModel | None = None
) -> StaffDocumentModel:
    model = existing if existing is not None else StaffDocumentModel(id=str(document.id))
    model.organization_id = str(document.organization_id)
    model.staff_id = str(document.staff_id)
    model.type_id = str(document.type_id)
    model.number = document.number
    model.issued_on = document.issued_on
    model.expires_on = document.expires_on
    model.notes = document.notes
    model.replaced_by_id = _str_or_none(document.replaced_by_id)
    model.alerted_threshold_days = document.alerted_threshold_days
    model.created_at = _to_naive_utc(document.created_at)
    model.updated_at = _to_naive_utc(document.updated_at)
    return model


def model_to_staff_document(model: StaffDocumentModel) -> StaffDocument:
    return StaffDocument(
        id=StaffDocumentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        staff_id=TransportStaffId(model.staff_id),
        type_id=StaffDocumentTypeId(model.type_id),
        number=model.number,
        issued_on=model.issued_on,
        expires_on=model.expires_on,
        notes=model.notes,
        replaced_by_id=StaffDocumentId(model.replaced_by_id) if model.replaced_by_id else None,
        alerted_threshold_days=model.alerted_threshold_days,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# ---- ADR-0052/0053 ------------------------------------------------------------------------------


def _id_or_none(cls, value: str | None):
    return cls(value.strip()) if value else None


def route_timetable_entry_to_model(
    entry: RouteTimetableEntry, *, existing: RouteTimetableEntryModel | None = None
) -> RouteTimetableEntryModel:
    model = existing if existing is not None else RouteTimetableEntryModel(id=str(entry.id))
    model.organization_id = str(entry.organization_id)
    model.route_id = str(entry.route_id)
    model.vehicle_id = str(entry.vehicle_id)
    model.trip_type = entry.trip_type.value
    model.weekdays = list(entry.weekdays)
    model.planned_departure = entry.planned_departure
    model.default_driver_id = str(entry.default_driver_id)
    model.valid_from = entry.valid_from
    model.valid_until = entry.valid_until
    model.is_active = entry.is_active
    model.created_at = _to_naive_utc(entry.created_at)
    model.updated_at = _to_naive_utc(entry.updated_at)
    return model


def model_to_route_timetable_entry(model: RouteTimetableEntryModel) -> RouteTimetableEntry:
    return RouteTimetableEntry(
        id=RouteTimetableEntryId(model.id.strip()),
        organization_id=OrganizationId(model.organization_id.strip()),
        route_id=RouteId(model.route_id.strip()),
        vehicle_id=VehicleId(model.vehicle_id.strip()),
        trip_type=TripType(model.trip_type),
        weekdays=tuple(model.weekdays or ()),
        planned_departure=model.planned_departure,
        default_driver_id=DriverId(model.default_driver_id.strip()),
        valid_from=model.valid_from,
        valid_until=model.valid_until,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def operating_closure_to_model(
    closure: OperatingClosure, *, existing: OperatingClosureModel | None = None
) -> OperatingClosureModel:
    model = existing if existing is not None else OperatingClosureModel(id=str(closure.id))
    model.organization_id = str(closure.organization_id)
    model.starts_on = closure.starts_on
    model.ends_on = closure.ends_on
    model.label = closure.label
    model.withdrawn_at = _to_naive_utc(closure.withdrawn_at)
    model.created_at = _to_naive_utc(closure.created_at)
    model.updated_at = _to_naive_utc(closure.updated_at)
    return model


def model_to_operating_closure(model: OperatingClosureModel) -> OperatingClosure:
    return OperatingClosure(
        id=OperatingClosureId(model.id.strip()),
        organization_id=OrganizationId(model.organization_id.strip()),
        starts_on=model.starts_on,
        ends_on=model.ends_on,
        label=model.label,
        withdrawn_at=model.withdrawn_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def staff_unavailability_to_model(
    item: StaffUnavailability, *, existing: StaffUnavailabilityModel | None = None
) -> StaffUnavailabilityModel:
    model = existing if existing is not None else StaffUnavailabilityModel(id=str(item.id))
    model.organization_id = str(item.organization_id)
    model.staff_id = str(item.staff_id)
    model.starts_on = item.starts_on
    model.ends_on = item.ends_on
    model.reason = item.reason.value
    model.note = item.note
    model.withdrawn_at = _to_naive_utc(item.withdrawn_at)
    model.created_at = _to_naive_utc(item.created_at)
    model.updated_at = _to_naive_utc(item.updated_at)
    return model


def model_to_staff_unavailability(model: StaffUnavailabilityModel) -> StaffUnavailability:
    return StaffUnavailability(
        id=StaffUnavailabilityId(model.id.strip()),
        organization_id=OrganizationId(model.organization_id.strip()),
        staff_id=TransportStaffId(model.staff_id.strip()),
        starts_on=model.starts_on,
        ends_on=model.ends_on,
        reason=UnavailabilityReason(model.reason),
        note=model.note,
        withdrawn_at=model.withdrawn_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def staff_cover_to_model(cover: StaffCover, *, existing: StaffCoverModel | None = None) -> StaffCoverModel:
    model = existing if existing is not None else StaffCoverModel(id=str(cover.id))
    model.organization_id = str(cover.organization_id)
    model.unavailability_id = str(cover.unavailability_id)
    model.absent_staff_id = str(cover.absent_staff_id)
    model.substitute_staff_id = str(cover.substitute_staff_id)
    model.vehicle_id = str(cover.vehicle_id)
    model.starts_on = cover.starts_on
    model.ends_on = cover.ends_on
    model.assignment_id = _str_or_none(cover.assignment_id)
    model.withdrawn_at = _to_naive_utc(cover.withdrawn_at)
    model.created_at = _to_naive_utc(cover.created_at)
    model.updated_at = _to_naive_utc(cover.updated_at)
    return model


def model_to_staff_cover(model: StaffCoverModel) -> StaffCover:
    return StaffCover(
        id=StaffCoverId(model.id.strip()),
        organization_id=OrganizationId(model.organization_id.strip()),
        unavailability_id=StaffUnavailabilityId(model.unavailability_id.strip()),
        absent_staff_id=TransportStaffId(model.absent_staff_id.strip()),
        substitute_staff_id=TransportStaffId(model.substitute_staff_id.strip()),
        vehicle_id=VehicleId(model.vehicle_id.strip()),
        starts_on=model.starts_on,
        ends_on=model.ends_on,
        assignment_id=_id_or_none(VehicleStaffAssignmentId, model.assignment_id),
        withdrawn_at=model.withdrawn_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
