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

from datetime import date, datetime

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
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from raad.core.db.base import Base
from raad.core.db.mixins import AuditedTableMixin

_STUDENT_STATUS_VALUES = ("active", "disabled", "graduated", "transferred")
_PARENT_STATUS_VALUES = ("active", "inactive")
_DRIVER_STATUS_VALUES = ("active", "inactive")
_ROUTE_STATUS_VALUES = ("active", "inactive")
_TRIP_TYPE_VALUES = ("morning", "afternoon")
_TRIP_STATUS_VALUES = ("scheduled", "in_progress", "interrupted", "completed")
_STUDENT_ASSIGNMENT_STATUS_VALUES = (
    "active",
    "removed",
    "transferred",
    "graduated",
    "disabled",
)


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
    pickup_stop_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("stops.id"), nullable=False
    )
    dropoff_stop_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("stops.id"), nullable=False
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
