"""transport_ops: timetable, closed days, unavailability, cover, trip cancellation (ADR-0052..0054)

Revision ID: b8e4f1a2c6d3
Revises: a7d3e9c1f4b2
Create Date: 2026-09-30 14:00:00.000000

Phase 2 of the transport-management roadmap ("Daily Transport Operations").

**Schema:**

- `trip_status` gains `cancelled` (ADR-0054). `ALTER TYPE ... ADD VALUE` runs in an autocommit
  block: PostgreSQL refuses to use a new enum value in the transaction that added it, and the
  partial index below compares against it.
- `trips` gains `timetable_entry_id`, `planned_departure`, `cancelled_at`, `cancelled_reason`
  and `coverage_alert_key`.
- `ux_trips__vehicle_date_type`: one non-cancelled trip per bus, date and period (ADR-0052 §3).
- New tables `route_timetable_entries`, `operating_closures`, `staff_unavailability` (with the
  `unavailability_reason` enum) and `staff_covers`.
- RBAC grants for every new permission: manage/generate/cancel to `org_admin`; list/read to
  founder, regional_manager and support_staff. None to finance_staff, driver or parent.

**Refusals, never repairs.** If existing trips already break the new uniqueness rule, the
upgrade stops and names them; it deletes and cancels nothing. The downgrade stops while any trip
is cancelled, rather than rewriting that history.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8e4f1a2c6d3"
down_revision: Union[str, None] = "a7d3e9c1f4b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRIP_TYPE = postgresql.ENUM("morning", "afternoon", name="trip_type", create_type=False)
_TRIP_STATUS_BEFORE = ("scheduled", "in_progress", "interrupted", "completed")

_ROLE_VALUES = (
    "founder",
    "regional_manager",
    "support_staff",
    "finance_staff",
    "org_admin",
    "driver",
    "parent",
)
_ORG_ADMIN_ONLY = (
    "transport_ops.timetable.manage",
    "transport_ops.closures.manage",
    "transport_ops.unavailability.manage",
    "transport_ops.covers.manage",
    "transport_ops.trips.generate",
    "transport_ops.trips.cancel",
)
_READ = (
    "transport_ops.timetable.list",
    "transport_ops.closures.list",
    "transport_ops.unavailability.list",
    "transport_ops.daily_operations.read",
)
_GRANTS: tuple[tuple[str, str], ...] = (
    *((("org_admin", p) for p in _ORG_ADMIN_ONLY + _READ)),
    *((("founder", p) for p in _READ)),
    *((("regional_manager", p) for p in _READ)),
    *((("support_staff", p) for p in _READ)),
)
_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("created_by", sa.CHAR(26), nullable=True),
        sa.Column("updated_by", sa.CHAR(26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            "SELECT vehicle_id, scheduled_date, trip_type, COUNT(*) FROM trips "
            "WHERE deleted_at IS NULL GROUP BY vehicle_id, scheduled_date, trip_type "
            "HAVING COUNT(*) > 1 ORDER BY scheduled_date LIMIT 20"
        )
    ).fetchall()
    if duplicates:
        listed = "; ".join(f"{d[0].strip()} {d[1]} {d[2]} x{d[3]}" for d in duplicates)
        raise RuntimeError(
            "b8e4f1a2c6d3 refused: these buses already have more than one trip for the same date "
            f"and period, which the new uniqueness rule cannot hold: {listed}. Resolve them "
            "first; this migration deletes and cancels nothing."
        )

    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE trip_status ADD VALUE IF NOT EXISTS 'cancelled'")

    op.create_table(
        "route_timetable_entries",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("route_id", sa.CHAR(26), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(26), nullable=False),
        sa.Column("trip_type", _TRIP_TYPE, nullable=False),
        sa.Column("weekdays", postgresql.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("planned_departure", sa.Time(), nullable=True),
        sa.Column("default_driver_id", sa.CHAR(26), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], name=op.f("fk_route_timetable_entries__routes")),
        sa.ForeignKeyConstraint(
            ["default_driver_id"], ["drivers.id"], name=op.f("fk_route_timetable_entries__drivers")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_route_timetable_entries")),
    )
    for column in ("organization_id", "route_id", "vehicle_id"):
        op.create_index(
            op.f(f"ix_route_timetable_entries__{column}"), "route_timetable_entries", [column]
        )

    op.create_table(
        "operating_closures",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("label", sa.VARCHAR(120), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=False), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operating_closures")),
    )
    op.create_index(op.f("ix_operating_closures__organization_id"), "operating_closures", ["organization_id"])
    op.create_index(
        "ix_operating_closures__organization_id_period",
        "operating_closures",
        ["organization_id", "starts_on", "ends_on"],
    )

    op.create_table(
        "staff_unavailability",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("staff_id", sa.CHAR(26), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum("sick", "personal", "training", "other", name="unavailability_reason"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(
            ["staff_id"], ["transport_staff.id"], name=op.f("fk_staff_unavailability__transport_staff")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_unavailability")),
    )
    op.create_index(op.f("ix_staff_unavailability__organization_id"), "staff_unavailability", ["organization_id"])
    op.create_index(op.f("ix_staff_unavailability__staff_id"), "staff_unavailability", ["staff_id"])
    op.create_index(
        "ix_staff_unavailability__organization_id_period",
        "staff_unavailability",
        ["organization_id", "starts_on", "ends_on"],
    )

    op.create_table(
        "staff_covers",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("unavailability_id", sa.CHAR(26), nullable=False),
        sa.Column("absent_staff_id", sa.CHAR(26), nullable=False),
        sa.Column("substitute_staff_id", sa.CHAR(26), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(26), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("assignment_id", sa.CHAR(26), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(
            ["unavailability_id"], ["staff_unavailability.id"], name=op.f("fk_staff_covers__staff_unavailability")
        ),
        sa.ForeignKeyConstraint(["absent_staff_id"], ["transport_staff.id"], name="fk_staff_covers__absent_staff"),
        sa.ForeignKeyConstraint(
            ["substitute_staff_id"], ["transport_staff.id"], name="fk_staff_covers__substitute_staff"
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["vehicle_staff_assignments.id"], name=op.f("fk_staff_covers__vehicle_staff_assignments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_covers")),
    )
    op.create_index(op.f("ix_staff_covers__organization_id"), "staff_covers", ["organization_id"])
    op.create_index(op.f("ix_staff_covers__unavailability_id"), "staff_covers", ["unavailability_id"])
    op.create_index(op.f("ix_staff_covers__substitute_staff_id"), "staff_covers", ["substitute_staff_id"])
    op.create_index(
        "ix_staff_covers__organization_id_period", "staff_covers", ["organization_id", "starts_on", "ends_on"]
    )

    op.add_column("trips", sa.Column("timetable_entry_id", sa.CHAR(26), nullable=True))
    op.add_column("trips", sa.Column("planned_departure", sa.Time(), nullable=True))
    op.add_column("trips", sa.Column("cancelled_at", sa.DateTime(timezone=False), nullable=True))
    op.add_column("trips", sa.Column("cancelled_reason", sa.VARCHAR(255), nullable=True))
    op.add_column("trips", sa.Column("coverage_alert_key", sa.VARCHAR(64), nullable=True))
    op.create_foreign_key(
        op.f("fk_trips__route_timetable_entries"), "trips", "route_timetable_entries", ["timetable_entry_id"], ["id"]
    )
    op.create_index(op.f("ix_trips__timetable_entry_id"), "trips", ["timetable_entry_id"])
    op.create_index(
        "ux_trips__vehicle_date_type",
        "trips",
        ["vehicle_id", "scheduled_date", "trip_type"],
        unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
    )

    op.bulk_insert(
        _role_permissions_table,
        [{"role": role, "permission": permission} for role, permission in _GRANTS],
    )


def downgrade() -> None:
    bind = op.get_bind()
    cancelled = bind.execute(sa.text("SELECT COUNT(*) FROM trips WHERE status = 'cancelled'")).scalar()
    if cancelled:
        raise RuntimeError(
            f"b8e4f1a2c6d3 downgrade refused: {cancelled} trip(s) are cancelled, and the older "
            "trip status has no value to hold them. History is not rewritten by a migration."
        )

    for role, permission in _GRANTS:
        op.execute(
            _role_permissions_table.delete().where(
                _role_permissions_table.c.role == role,
                _role_permissions_table.c.permission == permission,
            )
        )

    op.drop_index("ux_trips__vehicle_date_type", table_name="trips")
    op.drop_index(op.f("ix_trips__timetable_entry_id"), table_name="trips")
    op.drop_constraint(op.f("fk_trips__route_timetable_entries"), "trips", type_="foreignkey")
    for column in ("coverage_alert_key", "cancelled_reason", "cancelled_at", "planned_departure", "timetable_entry_id"):
        op.drop_column("trips", column)

    op.drop_table("staff_covers")
    op.drop_table("staff_unavailability")
    op.drop_table("operating_closures")
    op.drop_table("route_timetable_entries")
    sa.Enum(name="unavailability_reason").drop(bind, checkfirst=True)

    # Remove `cancelled` from trip_status: PostgreSQL cannot drop an enum value, so the type is
    # rebuilt. The partial index comparing `status` is dropped and recreated around the swap.
    op.drop_index("ux_trips__active_vehicle", table_name="trips")
    op.execute("ALTER TYPE trip_status RENAME TO trip_status_with_cancelled")
    values = ", ".join(f"'{v}'" for v in _TRIP_STATUS_BEFORE)
    op.execute(f"CREATE TYPE trip_status AS ENUM ({values})")
    op.execute("ALTER TABLE trips ALTER COLUMN status TYPE trip_status USING status::text::trip_status")
    op.execute("DROP TYPE trip_status_with_cancelled")
    op.create_index(
        "ux_trips__active_vehicle",
        "trips",
        ["vehicle_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )
