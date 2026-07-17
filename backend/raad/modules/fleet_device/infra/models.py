"""Fleet & Device ORM models (Backend LLD §17 `db`; Database Design §5.1–§5.4). SQLAlchemy is
confined to this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2).

Mixin usage follows each table's own Database Design entry, the same reading
`iam.infra.models` established: `vehicles`/`devices`/`cameras` each carry
"+ standard audit cols" (§5.1/§5.2/§5.3) → `AuditedTableMixin` (the full bundle);
`device_assignments` (§5.4) has **no** such line — its own `assigned_at`/`unassigned_at`
already serve the equivalent purpose and history rows are immutable audit data — so it
composes `UlidPrimaryKeyMixin` only, exactly like `RefreshTokenModel`.

`organization_id` on every table is an **indexed plain column, not a database FK**: it
references the `organization` module's table, and cross-context references are by ID only
(`.claude/rules/database.md` #3) — the same treatment `users.organization_id` already gets,
even though the Database Design table shorthand writes "FK, ix". In-context references
(`cameras.device_id`, `device_assignments.device_id`/`vehicle_id`) are real database-enforced
FKs, per the same rule.

The §5.4 "one active binding per device & per vehicle" invariant is implemented via two
**PostgreSQL partial unique indexes** (`ux_device_assignments__active_device` on `device_id`,
`ux_device_assignments__active_vehicle` on `vehicle_id`, each `WHERE unassigned_at IS NULL`) —
PostgreSQL's native mechanism for this exact constraint shape (ADR-0002). This supersedes the
original MySQL design, which had no native partial-index feature and instead emulated one with
two `Computed` generated columns (`active_device_key`/`active_vehicle_key`) each carrying a
plain unique index; PostgreSQL needs no denormalized key column at all, so neither column nor
its DB-maintenance concern exists anymore.

Index/constraint names follow `core.db.base`'s naming convention off the real column names
(e.g. `ux_vehicles__organization_id_plate_no`, not the doc's abbreviated
`ux_vehicles__org_plate`) — the same documented stance as `OrganizationModel` (Phase 6.3).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CHAR,
    VARCHAR,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from raad.core.db.base import Base
from raad.core.db.mixins import AuditedTableMixin, UlidPrimaryKeyMixin

_VEHICLE_STATUS_VALUES = ("active", "inactive", "maintenance")
_DEVICE_LIFECYCLE_VALUES = (
    "registered",
    "activated",
    "assigned",
    "suspended",
    "retired",
)
_CAMERA_POSITION_VALUES = ("in_cabin", "road_facing", "other")


class VehicleModel(AuditedTableMixin, Base):
    """`vehicles` (Database Design §5.1): the bus as a fleet asset. Per-tenant plate
    uniqueness via the composite unique constraint."""

    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("organization_id", "plate_no"),)

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    plate_no: Mapped[str] = mapped_column(VARCHAR(32), nullable=False)
    label: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_VEHICLE_STATUS_VALUES, name="vehicle_status"),
        nullable=False,
        index=True,
    )


class DeviceModel(AuditedTableMixin, Base):
    """`devices` (Database Design §5.2): the GPS/MDVR terminal. `last_seen_at` is a durable
    mirror of device-plane runtime state (written by a later phase's event consumer);
    `auth_key_hash` stays NULL pending an approved provisioning workflow (Phase 7.2's
    documented decision)."""

    __tablename__ = "devices"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    terminal_id: Mapped[str] = mapped_column(VARCHAR(64), nullable=False, unique=True)
    model: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    vendor: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    sim_msisdn: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(
        SqlEnum(*_DEVICE_LIFECYCLE_VALUES, name="device_lifecycle_state"),
        nullable=False,
        index=True,
    )
    auth_key_hash: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    # Camera child rows load eagerly with the device (selectin) — the Device aggregate owns
    # its cameras (Phase 7.1), so a Device is never materialized without them.
    cameras: Mapped[list["CameraModel"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CameraModel.channel_no",
    )


class CameraModel(AuditedTableMixin, Base):
    """`cameras` (Database Design §5.3): child of `devices` (in-context FK, DB-enforced).
    `organization_id` is the documented denormalized tenant key for scoping."""

    __tablename__ = "cameras"
    __table_args__ = (UniqueConstraint("device_id", "channel_no"),)

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("devices.id"), nullable=False, index=True
    )
    channel_no: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    position: Mapped[str] = mapped_column(
        SqlEnum(*_CAMERA_POSITION_VALUES, name="camera_position"), nullable=False
    )

    device: Mapped[DeviceModel] = relationship(back_populates="cameras")


class DeviceAssignmentModel(UlidPrimaryKeyMixin, Base):
    """`device_assignments` (Database Design §5.4): device↔vehicle binding history.
    `unassigned_at IS NULL` = active. The one-active-binding invariant's database half is the
    two partial unique indexes declared in `__table_args__` below (ADR-0002); the
    application-layer repository guard is the other half (Phase 7.2)."""

    __tablename__ = "device_assignments"
    __table_args__ = (
        Index(
            "ux_device_assignments__active_device",
            "device_id",
            unique=True,
            postgresql_where="unassigned_at IS NULL",
        ),
        Index(
            "ux_device_assignments__active_vehicle",
            "vehicle_id",
            unique=True,
            postgresql_where="unassigned_at IS NULL",
        ),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("devices.id"), nullable=False, index=True
    )
    vehicle_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("vehicles.id"), nullable=False, index=True
    )
    assigned_by: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
