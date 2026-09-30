"""tracking + transport_ops: safety alerts and the incident log (ADR-0055, ADR-0056)

Revision ID: c9f2a4e6b1d7
Revises: b8e4f1a2c6d3
Create Date: 2026-09-30 19:00:00.000000

Phase 3 of the transport-management roadmap ("Safety & Incidents").

- `safety_alerts` (tracking): one row per device alarm that started, with a partial unique index
  keeping one open alert per bus and type (a repeat updates it). `vehicle_id`, `trip_id`,
  `driver_id` and `incident_id` are cross-module ids with no foreign key.
- `incidents` and `incident_notes` (transport_ops): the operational incident log and its
  append-only timeline. Staff and students involved are id arrays checked by the service.
- RBAC: `tracking.safety_alerts.list` and `transport_ops.incidents.{list,read}` to org_admin,
  founder, regional_manager and support_staff; `.manage` to org_admin only. None to
  finance_staff, driver or parent.

Nothing is backfilled: raw `vehicle_positions.alarm_flags` history is not replayed into alerts.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9f2a4e6b1d7"
down_revision: Union[str, None] = "b8e4f1a2c6d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE_VALUES = (
    "founder",
    "regional_manager",
    "support_staff",
    "finance_staff",
    "org_admin",
    "driver",
    "parent",
)
_MANAGE = ("tracking.safety_alerts.manage", "transport_ops.incidents.manage")
_READ = ("tracking.safety_alerts.list", "transport_ops.incidents.list", "transport_ops.incidents.read")
_GRANTS: tuple[tuple[str, str], ...] = (
    *((("org_admin", p) for p in _MANAGE + _READ)),
    *((("founder", p) for p in _READ)),
    *((("regional_manager", p) for p in _READ)),
    *((("support_staff", p) for p in _READ)),
)
_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)
_TYPES = ("safety_alert_status", "incident_category", "incident_severity", "incident_status", "incident_note_kind")


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
    op.create_table(
        "safety_alerts",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(26), nullable=False),
        sa.Column("device_id", sa.CHAR(26), nullable=True),
        sa.Column("terminal_id", sa.VARCHAR(32), nullable=False),
        sa.Column("alarm_type", sa.VARCHAR(32), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "acknowledged", "resolved", "false_alarm", name="safety_alert_status"),
            nullable=False,
        ),
        sa.Column("raised_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("last_raised_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("speed_kph", sa.Float(), nullable=True),
        sa.Column("trip_id", sa.CHAR(26), nullable=True),
        sa.Column("driver_id", sa.CHAR(26), nullable=True),
        sa.Column("incident_id", sa.CHAR(26), nullable=True),
        sa.Column("device_confirmation", sa.VARCHAR(16), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=False), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_safety_alerts")),
    )
    op.create_index(op.f("ix_safety_alerts__organization_id"), "safety_alerts", ["organization_id"])
    op.create_index(
        "ix_safety_alerts__organization_id_raised_at", "safety_alerts", ["organization_id", "raised_at"]
    )
    op.create_index(
        "ux_safety_alerts__open_vehicle_type",
        "safety_alerts",
        ["vehicle_id", "alarm_type"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'acknowledged')"),
    )

    op.create_table(
        "incidents",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "accident", "breakdown", "medical", "behaviour", "near_miss", "delay",
                "student_left_behind", "other", name="incident_category",
            ),
            nullable=False,
        ),
        sa.Column("severity", sa.Enum("low", "medium", "high", "critical", name="incident_severity"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(26), nullable=True),
        sa.Column("trip_id", sa.CHAR(26), nullable=True),
        sa.Column("route_id", sa.CHAR(26), nullable=True),
        sa.Column("title", sa.VARCHAR(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("actions_taken", sa.Text(), nullable=True),
        sa.Column("staff_ids", postgresql.ARRAY(sa.CHAR(26)), nullable=False),
        sa.Column("student_ids", postgresql.ARRAY(sa.CHAR(26)), nullable=False),
        sa.Column(
            "status", sa.Enum("open", "investigating", "resolved", "closed", name="incident_status"), nullable=False
        ),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("recorded_in_error", sa.Boolean(), nullable=False),
        sa.Column("source_alert_id", sa.CHAR(26), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], name=op.f("fk_incidents__trips")),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], name=op.f("fk_incidents__routes")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(op.f("ix_incidents__organization_id"), "incidents", ["organization_id"])
    op.create_index(op.f("ix_incidents__vehicle_id"), "incidents", ["vehicle_id"])
    op.create_index("ix_incidents__organization_id_occurred_at", "incidents", ["organization_id", "occurred_at"])
    op.create_index("ix_incidents__organization_id_status", "incidents", ["organization_id", "status"])

    op.create_table(
        "incident_notes",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("incident_id", sa.CHAR(26), nullable=False),
        sa.Column(
            "kind", sa.Enum("note", "status_change", "parent_notice", name="incident_note_kind"), nullable=False
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_id", sa.CHAR(26), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], name=op.f("fk_incident_notes__incidents")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_notes")),
    )
    op.create_index(op.f("ix_incident_notes__organization_id"), "incident_notes", ["organization_id"])
    op.create_index(op.f("ix_incident_notes__incident_id"), "incident_notes", ["incident_id"])

    op.bulk_insert(
        _role_permissions_table,
        [{"role": role, "permission": permission} for role, permission in _GRANTS],
    )


def downgrade() -> None:
    for role, permission in _GRANTS:
        op.execute(
            _role_permissions_table.delete().where(
                _role_permissions_table.c.role == role,
                _role_permissions_table.c.permission == permission,
            )
        )
    op.drop_table("incident_notes")
    op.drop_table("incidents")
    op.drop_table("safety_alerts")
    bind = op.get_bind()
    for name in _TYPES:
        sa.Enum(name=name).drop(bind, checkfirst=True)
