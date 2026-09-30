"""Transport Operations ORM models (Backend LLD §17 `db`; Database Design §6.2/§6.3).
SQLAlchemy is confined to this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2).

`StudentModel` (`students`) and, as of Phase 10.6, `ParentModel` (`parents`). Both tables get
Database Design's "+ standard audit cols" line (§6.2/§6.3), the same reading
`organization.infra.models`/`fleet_device.infra.models` give their own audited tables, so both
compose `AuditedTableMixin` (the full bundle) — not a partial mixin set.

`organization_id` is an **indexed plain column, not a database FK**: it references the
`organization` module's own table, and cross-context references are by ID only
(`.claude/rules/database.md` #3) — the same treatment `users.organization_id`/
`vehicles.organization_id` already get. `ParentModel.user_id` is likewise a cross-context
reference (to `iam.UserModel`, Database Design §6.3's "FK→users" shorthand) — despite the
doc's "FK" wording, `users` is owned by `iam`, not `transport_ops`, so this is an indexed plain
column too, never a real `ForeignKey`, mirroring `organization_id`'s own treatment exactly
(see `domain/value_objects.py`'s `UserId` docstring for the full reasoning).

**Phase 10.7 addition: `StudentParentModel`.** `student_parents` (Database Design §6.4) is
composite-keyed by `(student_id, parent_id)` with no independent `id`/audit columns — §6.4
lists exactly four columns and no "+ standard audit cols" line, unlike every other table in
that document, including `students`/`parents` above (confirmed with the user before
implementing, since `.claude/rules/database.md` #4's general audit-column convention would
otherwise conflict with this table's own narrower, explicit spec). `student_id`/`parent_id`
**are** real database foreign keys here — unlike `organization_id`/`user_id` above — because
`students`, `parents`, and `student_parents` are all owned by this same module: in-context FKs
are enforced by the database (`.claude/rules/database.md` #3), the same treatment
`fleet_device.CameraModel.device_id → devices.id` already gets for an identical
same-module reference.

**Phase 10.8 addition: `DriverModel`.** `drivers` (Database Design §6.1, ADR-0001) gets the same
"+ standard audit cols" treatment as `students`/`parents` above, so it composes
`AuditedTableMixin` too. `organization_id`/`user_id` are indexed plain columns, not database
FKs — the identical cross-context-reference-by-ID-only treatment `ParentModel` already gets
(`.claude/rules/database.md` #3; `user_id` references `iam.UserModel`, despite Database Design
§6.1's "FK" shorthand). `license_no` uses `VARCHAR(64)` — Database Design §6.1 gives no explicit
length (compact notation), so this mirrors `StudentModel.external_ref`'s identical VARCHAR(64)
precedent for an unformatted identifier string (`domain/entities.py`'s Phase 10.8 addendum).

**Phase 11 addition: `RouteModel`/`StopModel`.** `routes` (§6.5) composes `AuditedTableMixin`
("+ standard audit cols") with a per-tenant unique constraint on `(organization_id, name)`,
mirroring `VehicleModel`'s identical `(organization_id, plate_no)` constraint
(`fleet_device.infra.models`). `stops` (§6.6) is a same-module in-context child of `routes`, so
`route_id` **is** a real database `ForeignKey` (unlike the cross-module `organization_id`/
`user_id` columns above), the identical treatment `CameraModel.device_id → devices.id` already
gets. `RouteModel.stops` is a `selectin`-eager relationship ordered by `sequence_no`, cascading
`all, delete-orphan` — a `Route` is never materialized without its stops, and removing a stop
from the aggregate's collection deletes its row, the exact shape
`fleet_device.infra.models.DeviceModel.cameras` already establishes for `Camera`, extended here
with delete support since `Route.remove_stop` exists (unlike `Device`, which has no
camera-removal domain behavior — `infra/mappers.py`'s Phase 11 addition explains the one
resulting difference in the mapper sync logic).

PostgreSQL types only (ADR-0002) — no MySQL dialect import anywhere in this file, matching
every other infra model rewritten during the PostgreSQL migration.

**Phase 12 addition: `TripModel`.** `trips` (§6.8) composes `AuditedTableMixin` ("+ standard
audit cols"). `driver_id`/`route_id` are real database `ForeignKey`s — in-context, same-module
references (`drivers.id`/`routes.id`), the identical treatment `stops.route_id` already gets;
`vehicle_id`/`organization_id` stay plain indexed columns — cross-module references, the same
`organization_id`/`user_id` treatment every other table in this file gets. The one-active-
trip-per-vehicle invariant (§6.8: "generated-column unique... = vehicle_id when
status=in_progress else NULL") is implemented the same way `device_assignments`'
one-active-binding invariant already is under ADR-0002: a **PostgreSQL partial unique index**
(`ux_trips__active_vehicle` on `vehicle_id`, `WHERE status = 'in_progress'`) rather than a
generated denormalized key column — no MySQL-emulation column exists here either. The plain
composite index `ix_trips__organization_id_scheduled_date_status` is §6.8's own documented
`ix_trips__org_date_status`.

**Phase 13 addition: `StudentAssignmentModel`.** `student_assignments` (§6.7) composes
`AuditedTableMixin` ("+ standard audit cols"). `student_id`/`route_id`/`pickup_stop_id`/
`dropoff_stop_id` are real database `ForeignKey`s — all four are same-module, in-context
references (`students.id`/`routes.id`/`stops.id`), the identical treatment `stops.route_id`
already gets; `vehicle_id`/`organization_id` stay plain indexed columns (cross-module/tenant
references). `vehicle_id` is additionally **nullable** — §6.7 marks it optional, unlike
`TripModel.vehicle_id` (`NOT NULL`). The one-active-assignment-per-student invariant (§6.7:
"generated-column unique... = student_id when status=active else NULL") is implemented the same
way `TripModel`'s one-active-trip-per-vehicle invariant already is: a **PostgreSQL partial
unique index** (`ux_student_assignments__active_student` on `student_id`,
`WHERE status = 'active'`), no generated denormalized key column. The two plain composite
indexes (`ix_student_assignments__organization_id_status`,
`ix_student_assignments__student_id_status`) are §6.7's own documented
`ix_student_assignments__org_status`/`ix_student_assignments__student_status`, expanded to real
column names per `core.db.base`'s naming convention (off the actual column names, not the
doc's abbreviated form — the same expansion `TripModel`'s own composite index above already
applies).
"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    CHAR,
    DECIMAL,
    VARCHAR,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Time,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from raad.core.db.base import Base
from raad.core.db.mixins import AuditedTableMixin

_STUDENT_STATUS_VALUES = ("active", "disabled", "graduated", "transferred")
_PARENT_STATUS_VALUES = ("active", "inactive")
_DRIVER_STATUS_VALUES = ("active", "inactive")
_ROUTE_STATUS_VALUES = ("active", "inactive")
_TRIP_TYPE_VALUES = ("morning", "afternoon")
_TRIP_STATUS_VALUES = ("scheduled", "in_progress", "interrupted", "completed", "cancelled")
_STUDENT_ASSIGNMENT_STATUS_VALUES = (
    "active",
    "removed",
    "transferred",
    "graduated",
    "disabled",
)
# 2026-09-10 explicit user directive (Parent & Student Domain Restructure) — additive profile
# fields, not in Database Design §6.2/§6.3. See `domain/value_objects.py`'s own module comment.
_GENDER_VALUES = ("male", "female", "other")


class StudentModel(AuditedTableMixin, Base):
    """`students` (Database Design §6.2): a student enrolled with an organization."""

    __tablename__ = "students"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_STUDENT_STATUS_VALUES, name="student_status"),
        nullable=False,
        index=True,
    )
    #: 2026-09-10 explicit user directive — additive, nullable, not in Database Design §6.2.
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(
        SqlEnum(*_GENDER_VALUES, name="student_gender"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(VARCHAR(500), nullable=True)


class ParentModel(AuditedTableMixin, Base):
    """`parents` (Database Design §6.3): a parent/guardian's transport-facing profile, linked
    to an `iam.User` login. `full_name`/`phone` use `VARCHAR(200)`/`VARCHAR(32)` — the lengths
    already established for the identically-named columns elsewhere in this schema
    (`users.full_name`/`users.phone`, `iam/infra/models.py`), since §6.3's compact notation
    gives no explicit lengths of its own (see `domain/value_objects.py`'s module docstring).
    """

    __tablename__ = "parents"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_PARENT_STATUS_VALUES, name="parent_status"),
        nullable=False,
        index=True,
    )
    #: ADR-0026: off by default, org_admin-grantable per parent. Kept as two independent
    #: booleans, not one "video_enabled" flag - live and playback are separately grantable.
    #: `default=False` mirrors `fleet_device.DeviceModel.is_online`'s identical precedent; the
    #: migration itself carries the `server_default` for existing rows.
    has_video_live_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_video_playback_access: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    #: 2026-09-10 explicit user directive — additive, nullable, not in Database Design §6.3.
    alternate_phone: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    address: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(VARCHAR(200), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(VARCHAR(500), nullable=True)


class StudentParentModel(Base):
    """`student_parents` (Database Design §6.4, M:N): see module docstring's Phase 10.7
    addition for why this composes `Base` directly rather than `AuditedTableMixin` (or any of
    its constituent mixins) — no `id`, no `created_at`/`updated_at`, no `row_version`, no
    `deleted_at`.

    `parent_id` carries an explicit secondary index: the composite PK `(student_id, parent_id)`
    only serves left-prefix lookups by `student_id` (`list_by_student`, `infra/repositories.py`)
    — `list_by_parent`'s `WHERE parent_id = ...` needs its own index, the same reasoning
    `fleet_device.CameraModel.device_id`/`DeviceAssignmentModel.vehicle_id` already get
    dedicated indexes for. `student_id` needs no equivalent index of its own — it's the PK's
    leading column, already covered."""

    __tablename__ = "student_parents"

    student_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("students.id"), primary_key=True
    )
    parent_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("parents.id"), primary_key=True, index=True
    )
    relationship: Mapped[str | None] = mapped_column(VARCHAR(40), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DriverModel(AuditedTableMixin, Base):
    """`drivers` (Database Design §6.1, ADR-0001): a vehicle operator's transport-facing
    profile, linked to an `iam.User` login. `license_no` uses `VARCHAR(64)` — see module
    docstring's Phase 10.8 addition for why."""

    __tablename__ = "drivers"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    license_no: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_DRIVER_STATUS_VALUES, name="driver_status"),
        nullable=False,
        index=True,
    )
    #: ADR-0049: the person this driver profile belongs to — one driver profile per person.
    staff_id: Mapped[str] = mapped_column(
        CHAR(26),
        ForeignKey("transport_staff.id"),
        nullable=False,
        unique=True,
    )


class RouteModel(AuditedTableMixin, Base):
    """`routes` (Database Design §6.5): a transportation path followed by a vehicle. Per-tenant
    name uniqueness via the composite unique constraint, mirroring `VehicleModel`'s identical
    `(organization_id, plate_no)` shape."""

    __tablename__ = "routes"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    name: Mapped[str] = mapped_column(VARCHAR(160), nullable=False)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_ROUTE_STATUS_VALUES, name="route_status"),
        nullable=False,
        index=True,
    )

    # Stop child rows load eagerly with the route (selectin) - the Route aggregate owns its
    # stops (Phase 11), so a Route is never materialized without them.
    stops: Mapped[list["StopModel"]] = relationship(
        back_populates="route",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="StopModel.sequence_no",
    )


class StopModel(AuditedTableMixin, Base):
    """`stops` (Database Design §6.6): child of `routes` (in-context FK, DB-enforced).
    `organization_id` is the documented denormalized tenant key for scoping, mirroring
    `CameraModel`'s identical treatment."""

    __tablename__ = "stops"
    __table_args__ = (UniqueConstraint("route_id", "sequence_no"),)

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    route_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("routes.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(VARCHAR(160), nullable=False)
    # asdecimal=False -> Python float, matching tracking.infra.models.VehiclePositionModel's
    # identical DECIMAL(9,6) lat/long columns exactly (Decimal would otherwise be the default
    # SQLAlchemy DECIMAL return type, mismatching Stop.latitude/longitude's `float` fields).
    latitude: Mapped[float] = mapped_column(
        DECIMAL(9, 6, asdecimal=False), nullable=False
    )
    longitude: Mapped[float] = mapped_column(
        DECIMAL(9, 6, asdecimal=False), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    geofence_radius_m: Mapped[int | None] = mapped_column(Integer, nullable=True)

    route: Mapped[RouteModel] = relationship(back_populates="stops")


class TripModel(AuditedTableMixin, Base):
    """`trips` (Database Design §6.8): the operational aggregate root for a day's journey."""

    __tablename__ = "trips"
    __table_args__ = (
        Index(
            "ux_trips__active_vehicle",
            "vehicle_id",
            unique=True,
            postgresql_where="status = 'in_progress'",
        ),
        Index(
            "ix_trips__organization_id_scheduled_date_status",
            "organization_id",
            "scheduled_date",
            "status",
        ),
        # ADR-0052 §3: one non-cancelled trip per bus, date and period.
        Index(
            "ux_trips__vehicle_date_type",
            "vehicle_id",
            "scheduled_date",
            "trip_type",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    vehicle_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    driver_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("drivers.id"), nullable=False, index=True
    )
    route_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("routes.id"), nullable=False, index=True
    )
    trip_type: Mapped[str] = mapped_column(
        SqlEnum(*_TRIP_TYPE_VALUES, name="trip_type"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        SqlEnum(*_TRIP_STATUS_VALUES, name="trip_status"),
        nullable=False,
        index=True,
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    #: ADR-0052: generated from this timetable entry, if any; departure copied at generation.
    timetable_entry_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("route_timetable_entries.id"), nullable=True, index=True
    )
    planned_departure: Mapped[time | None] = mapped_column(Time, nullable=True)
    #: ADR-0054.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    #: ADR-0053 §5: the last uncovered cause alerted.
    coverage_alert_key: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)


class StudentAssignmentModel(AuditedTableMixin, Base):
    """`student_assignments` (Database Design §6.7): "the CR-1 access gate" — binds a Student
    to a Route, pickup/dropoff Stop, and optionally a Vehicle."""

    __tablename__ = "student_assignments"
    __table_args__ = (
        Index(
            "ux_student_assignments__active_student",
            "student_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
        Index(
            "ix_student_assignments__organization_id_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_student_assignments__student_id_status",
            "student_id",
            "status",
        ),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("students.id"), nullable=False, index=True
    )
    route_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("routes.id"), nullable=False, index=True
    )
    # Explicit names required: two FKs to the same target table (`stops.id`) would otherwise
    # both collapse to the identical auto-derived name `fk_student_assignments__stops`
    # (`core/db/base.py`'s naming convention only encodes the *target* table, not the *source*
    # column) - PostgreSQL rejects two constraints sharing one name on the same table. Must
    # match the names the migration already created live
    # (`migrations/versions/20260719_1400_acfa30ebf4d8_..._student_.py`) exactly, since no new
    # migration accompanies this fix.
    pickup_stop_id: Mapped[str] = mapped_column(
        CHAR(26),
        ForeignKey("stops.id", name="fk_student_assignments__stops_pickup"),
        nullable=False,
    )
    dropoff_stop_id: Mapped[str] = mapped_column(
        CHAR(26),
        ForeignKey("stops.id", name="fk_student_assignments__stops_dropoff"),
        nullable=False,
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        CHAR(26), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        SqlEnum(*_STUDENT_ASSIGNMENT_STATUS_VALUES, name="student_assignment_status"),
        nullable=False,
        index=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )


# ---- ADR-0049/0050/0051: transport staff, bus crew, staff documents ----------------------------

_TRANSPORT_STAFF_STATUS_VALUES = ("active", "inactive", "left")
_STAFF_ASSIGNMENT_KIND_VALUES = ("permanent", "temporary")


class TransportStaffRoleModel(AuditedTableMixin, Base):
    """An organization's own job titles for bus crew (ADR-0049 §2)."""

    __tablename__ = "transport_staff_roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="ux_transport_staff_roles__org_name"),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    name: Mapped[str] = mapped_column(VARCHAR(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TransportStaffModel(AuditedTableMixin, Base):
    """The person record for everyone who works on a school bus (ADR-0049 §1). Phone numbers,
    the emergency contact and notes are personal data and are never copied into events."""

    __tablename__ = "transport_staff"
    __table_args__ = (
        # Unique within an organization only when set: many schools will not use references.
        Index(
            "ux_transport_staff__org_employee_ref",
            "organization_id",
            "employee_ref",
            unique=True,
            postgresql_where=text("employee_ref IS NOT NULL"),
        ),
        Index("ix_transport_staff__organization_id_status", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    alternate_phone: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    role_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("transport_staff_roles.id"), nullable=True, index=True
    )
    employee_ref: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_TRANSPORT_STAFF_STATUS_VALUES, name="transport_staff_status"),
        nullable=False,
    )
    emergency_contact_name: Mapped[str | None] = mapped_column(VARCHAR(200), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    left_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class VehicleStaffAssignmentModel(AuditedTableMixin, Base):
    """The bus crew and its history (ADR-0050). `vehicle_id` references `fleet_device` by id
    only, with no foreign key (`.claude/rules/database.md` #3); the application checks the bus
    belongs to the same organization. Rows are never deleted."""

    __tablename__ = "vehicle_staff_assignments"
    __table_args__ = (
        # One open-ended assignment per person per bus. Dated rows (temporary, or already
        # ended) are kept from overlapping by the application's overlap check.
        Index(
            "ux_vehicle_staff_assignments__open_staff_vehicle",
            "staff_id",
            "vehicle_id",
            unique=True,
            postgresql_where=text("ends_on IS NULL"),
        ),
        Index(
            "ix_vehicle_staff_assignments__vehicle_period",
            "vehicle_id",
            "starts_on",
            "ends_on",
        ),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    staff_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("transport_staff.id"), nullable=False, index=True
    )
    vehicle_id: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    role_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("transport_staff_roles.id"), nullable=True
    )
    route_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("routes.id"), nullable=True, index=True
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    kind: Mapped[str] = mapped_column(
        SqlEnum(*_STAFF_ASSIGNMENT_KIND_VALUES, name="staff_assignment_kind"),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)


class StaffDocumentTypeModel(AuditedTableMixin, Base):
    """An organization's own document kinds and their alert lead days (ADR-0051 §1)."""

    __tablename__ = "staff_document_types"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="ux_staff_document_types__org_name"),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    name: Mapped[str] = mapped_column(VARCHAR(80), nullable=False)
    alert_lead_days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class StaffDocumentModel(AuditedTableMixin, Base):
    """A staff member's credential: metadata only, never a file (ADR-0051 §2). `number` is
    personal data — Org Admin only, never in an event or a log."""

    __tablename__ = "staff_documents"
    __table_args__ = (
        Index(
            "ix_staff_documents__org_current_expiry",
            "organization_id",
            "expires_on",
            postgresql_where=text("replaced_by_id IS NULL AND deleted_at IS NULL"),
        ),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    staff_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("transport_staff.id"), nullable=False, index=True
    )
    type_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("staff_document_types.id"), nullable=False
    )
    number: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    issued_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Deferred to commit: a renewal inserts the new document and points the old one at it in
    #: one flush, and the flush emits a table's UPDATEs before its INSERTs.
    replaced_by_id: Mapped[str | None] = mapped_column(
        CHAR(26),
        ForeignKey("staff_documents.id", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    alerted_threshold_days: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


# ---- ADR-0052/0053: timetable, closures, unavailability, cover ------------------------------

_UNAVAILABILITY_REASON_VALUES = ("sick", "personal", "training", "other")


class RouteTimetableEntryModel(AuditedTableMixin, Base):
    """ADR-0052 §1: one regular run. `vehicle_id` is a cross-module id with no foreign key."""

    __tablename__ = "route_timetable_entries"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    route_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("routes.id"), nullable=False, index=True
    )
    vehicle_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    trip_type: Mapped[str] = mapped_column(
        SqlEnum(*_TRIP_TYPE_VALUES, name="trip_type", create_type=False), nullable=False
    )
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), nullable=False)
    planned_departure: Mapped[time | None] = mapped_column(Time, nullable=True)
    default_driver_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("drivers.id"), nullable=False
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class OperatingClosureModel(AuditedTableMixin, Base):
    """ADR-0052 §2: days without transport."""

    __tablename__ = "operating_closures"
    __table_args__ = (
        Index("ix_operating_closures__organization_id_period", "organization_id", "starts_on", "ends_on"),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str] = mapped_column(VARCHAR(120), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class StaffUnavailabilityModel(AuditedTableMixin, Base):
    """ADR-0053 §1. `note` is Org Admin only and never enters an event."""

    __tablename__ = "staff_unavailability"
    __table_args__ = (
        Index("ix_staff_unavailability__organization_id_period", "organization_id", "starts_on", "ends_on"),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    staff_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("transport_staff.id"), nullable=False, index=True
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(
        SqlEnum(*_UNAVAILABILITY_REASON_VALUES, name="unavailability_reason"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class StaffCoverModel(AuditedTableMixin, Base):
    """ADR-0053 §2: the substitute for one unavailability on one bus."""

    __tablename__ = "staff_covers"
    __table_args__ = (
        Index("ix_staff_covers__organization_id_period", "organization_id", "starts_on", "ends_on"),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    unavailability_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("staff_unavailability.id"), nullable=False, index=True
    )
    # Two foreign keys to one table: the naming convention would give both the same name.
    absent_staff_id: Mapped[str] = mapped_column(
        CHAR(26),
        ForeignKey("transport_staff.id", name="fk_staff_covers__absent_staff"),
        nullable=False,
    )
    substitute_staff_id: Mapped[str] = mapped_column(
        CHAR(26),
        ForeignKey("transport_staff.id", name="fk_staff_covers__substitute_staff"),
        nullable=False,
        index=True,
    )
    vehicle_id: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    assignment_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("vehicle_staff_assignments.id"), nullable=True
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
