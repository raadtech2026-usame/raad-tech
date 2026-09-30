"""transport_ops: transport staff, bus crew history, staff documents (ADR-0049/0050/0051)

Revision ID: a7d3e9c1f4b2
Revises: f6c2d9e1b3a8
Create Date: 2026-09-30 10:00:00.000000

Phase 1 of the transport people foundation.

**Schema:**

- `transport_staff_roles` — each organization's own job titles (ADR-0049 §2).
- `transport_staff` — one row per person who works on a bus (ADR-0049 §1). `employee_ref` is
  unique within an organization only when set (partial unique index).
- `vehicle_staff_assignments` — the bus crew and its history (ADR-0050). `vehicle_id` is a
  cross-module id with no foreign key (`.claude/rules/database.md` #3). A partial unique index
  allows one open-ended row per person per bus.
- `staff_document_types` / `staff_documents` — document metadata and expiry (ADR-0051). No
  file columns: RAAD stores no scans.
- `drivers.staff_id` — NOT NULL, unique, FK to `transport_staff`: every driver is a staff
  member, and one staff member has at most one driver profile.

**Backfill — nothing is invented.**

1. Every existing organization gets the default job titles (Driver, Attendant, Assistant,
   Conductor, Supervisor) and document types (each alerting at 30 and 7 days), so existing
   schools see a working page. New organizations start empty and use "Add defaults".
2. Every existing driver (including soft-deleted ones, since the column is NOT NULL) gets one
   staff record. Name and phone are copied from the driver's own login (`users.full_name`,
   `users.phone`) — the only place RAAD has ever held them. Status follows the driver's: an
   inactive driver becomes an inactive staff member, a soft-deleted driver a soft-deleted one.
   The title is the organization's seeded "Driver". No bus assignment is guessed: RAAD has
   never recorded which driver drives which bus outside a trip.
3. RBAC: `transport_ops.staff.*`, `.staff_roles.*`, `.staff_assignments.*`,
   `.staff_documents.*`. Manage goes to `org_admin` only; `founder`, `regional_manager` and
   `support_staff` get list/read. `finance_staff`, `driver` and `parent` get nothing.

`downgrade()` drops `drivers.staff_id` and every new table, type and grant. The staff rows it
drops held only copies of login data plus what admins entered after the upgrade; the latter is
lost, which is what a downgrade of a new feature means.
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from raad.core.ids.generator import generate_ulid

revision: str = "a7d3e9c1f4b2"
down_revision: Union[str, None] = "f6c2d9e1b3a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_ROLES = ("Driver", "Attendant", "Assistant", "Conductor", "Supervisor")
_DEFAULT_DOCUMENT_TYPES = (
    "Driving licence",
    "National ID/Passport",
    "Medical certificate",
    "Police clearance",
    "First-aid certificate",
    "Other",
)
_DEFAULT_LEAD_DAYS = [30, 7]

_ROLE_VALUES = (
    "founder",
    "regional_manager",
    "support_staff",
    "finance_staff",
    "org_admin",
    "driver",
    "parent",
)
_MANAGE = (
    "transport_ops.staff.list",
    "transport_ops.staff.read",
    "transport_ops.staff.manage",
    "transport_ops.staff_roles.list",
    "transport_ops.staff_roles.manage",
    "transport_ops.staff_assignments.list",
    "transport_ops.staff_assignments.manage",
    "transport_ops.staff_documents.list",
    "transport_ops.staff_documents.manage",
)
_READ = tuple(p for p in _MANAGE if not p.endswith(".manage"))
_GRANTS: tuple[tuple[str, str], ...] = (
    *((("org_admin", p) for p in _MANAGE)),
    *((("founder", p) for p in _READ)),
    *((("regional_manager", p) for p in _READ)),
    *((("support_staff", p) for p in _READ)),
)

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)

_DRIVER_STAFF_FK = "fk_drivers__transport_staff"
_DRIVER_STAFF_UNIQUE = "ux_drivers__staff_id"


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
        "transport_staff_roles",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("name", sa.VARCHAR(80), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transport_staff_roles")),
        sa.UniqueConstraint(
            "organization_id", "name", name="ux_transport_staff_roles__org_name"
        ),
    )
    op.create_index(
        op.f("ix_transport_staff_roles__organization_id"),
        "transport_staff_roles",
        ["organization_id"],
    )

    op.create_table(
        "transport_staff",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("full_name", sa.VARCHAR(200), nullable=False),
        sa.Column("phone", sa.VARCHAR(32), nullable=True),
        sa.Column("alternate_phone", sa.VARCHAR(32), nullable=True),
        sa.Column("role_id", sa.CHAR(26), nullable=True),
        sa.Column("employee_ref", sa.VARCHAR(64), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", "left", name="transport_staff_status"),
            nullable=False,
        ),
        sa.Column("emergency_contact_name", sa.VARCHAR(200), nullable=True),
        sa.Column("emergency_contact_phone", sa.VARCHAR(32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("left_on", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["transport_staff_roles.id"],
            name=op.f("fk_transport_staff__transport_staff_roles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transport_staff")),
    )
    op.create_index(
        op.f("ix_transport_staff__organization_id"), "transport_staff", ["organization_id"]
    )
    op.create_index(op.f("ix_transport_staff__role_id"), "transport_staff", ["role_id"])
    op.create_index(
        "ix_transport_staff__organization_id_status",
        "transport_staff",
        ["organization_id", "status"],
    )
    op.create_index(
        "ux_transport_staff__org_employee_ref",
        "transport_staff",
        ["organization_id", "employee_ref"],
        unique=True,
        postgresql_where=sa.text("employee_ref IS NOT NULL"),
    )

    op.create_table(
        "vehicle_staff_assignments",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("staff_id", sa.CHAR(26), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(26), nullable=False),
        sa.Column("role_id", sa.CHAR(26), nullable=True),
        sa.Column("route_id", sa.CHAR(26), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("permanent", "temporary", name="staff_assignment_kind"),
            nullable=False,
        ),
        sa.Column("reason", sa.VARCHAR(255), nullable=True),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["transport_staff.id"],
            name=op.f("fk_vehicle_staff_assignments__transport_staff"),
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["transport_staff_roles.id"],
            name=op.f("fk_vehicle_staff_assignments__transport_staff_roles"),
        ),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["routes.id"],
            name=op.f("fk_vehicle_staff_assignments__routes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_staff_assignments")),
    )
    op.create_index(
        op.f("ix_vehicle_staff_assignments__organization_id"),
        "vehicle_staff_assignments",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_vehicle_staff_assignments__staff_id"),
        "vehicle_staff_assignments",
        ["staff_id"],
    )
    op.create_index(
        op.f("ix_vehicle_staff_assignments__route_id"),
        "vehicle_staff_assignments",
        ["route_id"],
    )
    op.create_index(
        "ix_vehicle_staff_assignments__vehicle_period",
        "vehicle_staff_assignments",
        ["vehicle_id", "starts_on", "ends_on"],
    )
    op.create_index(
        "ux_vehicle_staff_assignments__open_staff_vehicle",
        "vehicle_staff_assignments",
        ["staff_id", "vehicle_id"],
        unique=True,
        postgresql_where=sa.text("ends_on IS NULL"),
    )

    op.create_table(
        "staff_document_types",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("name", sa.VARCHAR(80), nullable=False),
        sa.Column("alert_lead_days", postgresql.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_document_types")),
        sa.UniqueConstraint(
            "organization_id", "name", name="ux_staff_document_types__org_name"
        ),
    )
    op.create_index(
        op.f("ix_staff_document_types__organization_id"),
        "staff_document_types",
        ["organization_id"],
    )

    op.create_table(
        "staff_documents",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("staff_id", sa.CHAR(26), nullable=False),
        sa.Column("type_id", sa.CHAR(26), nullable=False),
        sa.Column("number", sa.VARCHAR(64), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("replaced_by_id", sa.CHAR(26), nullable=True),
        sa.Column("alerted_threshold_days", sa.SmallInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["transport_staff.id"],
            name=op.f("fk_staff_documents__transport_staff"),
        ),
        sa.ForeignKeyConstraint(
            ["type_id"],
            ["staff_document_types.id"],
            name=op.f("fk_staff_documents__staff_document_types"),
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["staff_documents.id"],
            name=op.f("fk_staff_documents__staff_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_documents")),
    )
    op.create_index(
        op.f("ix_staff_documents__organization_id"), "staff_documents", ["organization_id"]
    )
    op.create_index(op.f("ix_staff_documents__staff_id"), "staff_documents", ["staff_id"])
    op.create_index(
        "ix_staff_documents__org_current_expiry",
        "staff_documents",
        ["organization_id", "expires_on"],
        postgresql_where=sa.text("replaced_by_id IS NULL AND deleted_at IS NULL"),
    )

    op.add_column("drivers", sa.Column("staff_id", sa.CHAR(26), nullable=True))

    _backfill()

    op.alter_column("drivers", "staff_id", existing_type=sa.CHAR(26), nullable=False)
    op.create_unique_constraint(_DRIVER_STAFF_UNIQUE, "drivers", ["staff_id"])
    op.create_foreign_key(
        _DRIVER_STAFF_FK, "drivers", "transport_staff", ["staff_id"], ["id"]
    )

    op.bulk_insert(
        _role_permissions_table,
        [{"role": role, "permission": permission} for role, permission in _GRANTS],
    )


def _backfill() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    organizations = [
        row.id for row in bind.execute(sa.text("SELECT id FROM organizations")).fetchall()
    ]
    driver_role: dict[str, str] = {}
    for organization_id in organizations:
        for position, name in enumerate(_DEFAULT_ROLES, start=1):
            role_id = generate_ulid()
            if name == "Driver":
                driver_role[organization_id] = role_id
            bind.execute(
                sa.text(
                    "INSERT INTO transport_staff_roles (id, created_at, updated_at, "
                    "row_version, organization_id, name, sort_order, is_archived) "
                    "VALUES (:id, :now, :now, 1, :org, :name, :sort, false)"
                ),
                {"id": role_id, "now": now, "org": organization_id, "name": name,
                 "sort": position * 10},
            )
        for name in _DEFAULT_DOCUMENT_TYPES:
            bind.execute(
                sa.text(
                    "INSERT INTO staff_document_types (id, created_at, updated_at, "
                    "row_version, organization_id, name, alert_lead_days, is_archived) "
                    "VALUES (:id, :now, :now, 1, :org, :name, :lead, false)"
                ),
                {"id": generate_ulid(), "now": now, "org": organization_id, "name": name,
                 "lead": _DEFAULT_LEAD_DAYS},
            )

    drivers = bind.execute(
        sa.text(
            "SELECT d.id, d.organization_id, d.status, d.created_at, d.deleted_at, "
            "u.full_name, u.phone "
            "FROM drivers d LEFT JOIN users u ON u.id = d.user_id"
        )
    ).fetchall()
    missing_login = 0
    for driver in drivers:
        staff_id = generate_ulid()
        full_name = (driver.full_name or "").strip()
        if not full_name:
            # A driver whose login row is gone still needs a person record; name it by its
            # own id rather than inventing a name.
            missing_login += 1
            full_name = f"Driver {driver.id.strip()}"
        organization_id = driver.organization_id.strip()
        bind.execute(
            sa.text(
                "INSERT INTO transport_staff (id, created_at, updated_at, row_version, "
                "deleted_at, organization_id, full_name, phone, role_id, status) "
                "VALUES (:id, :created, :now, 1, :deleted, :org, :name, :phone, :role, "
                ":status)"
            ),
            {
                "id": staff_id,
                "created": driver.created_at,
                "now": now,
                "deleted": driver.deleted_at,
                "org": organization_id,
                "name": full_name,
                "phone": driver.phone,
                "role": driver_role.get(organization_id),
                "status": "active" if driver.status == "active" else "inactive",
            },
        )
        bind.execute(
            sa.text("UPDATE drivers SET staff_id = :staff WHERE id = :id"),
            {"staff": staff_id, "id": driver.id},
        )

    print(
        f"a7d3e9c1f4b2: default titles and document types seeded for {len(organizations)} "
        f"organization(s); {len(drivers)} staff record(s) created from existing drivers"
        + (f" ({missing_login} without a login row, named by driver id)" if missing_login else "")
        + "."
    )


def downgrade() -> None:
    for role, permission in _GRANTS:
        op.execute(
            _role_permissions_table.delete().where(
                _role_permissions_table.c.role == role,
                _role_permissions_table.c.permission == permission,
            )
        )

    op.drop_constraint(_DRIVER_STAFF_FK, "drivers", type_="foreignkey")
    op.drop_constraint(_DRIVER_STAFF_UNIQUE, "drivers", type_="unique")
    op.drop_column("drivers", "staff_id")

    op.drop_index("ix_staff_documents__org_current_expiry", table_name="staff_documents")
    op.drop_index(op.f("ix_staff_documents__staff_id"), table_name="staff_documents")
    op.drop_index(op.f("ix_staff_documents__organization_id"), table_name="staff_documents")
    op.drop_table("staff_documents")

    op.drop_index(
        op.f("ix_staff_document_types__organization_id"), table_name="staff_document_types"
    )
    op.drop_table("staff_document_types")

    op.drop_index(
        "ux_vehicle_staff_assignments__open_staff_vehicle",
        table_name="vehicle_staff_assignments",
    )
    op.drop_index(
        "ix_vehicle_staff_assignments__vehicle_period", table_name="vehicle_staff_assignments"
    )
    op.drop_index(
        op.f("ix_vehicle_staff_assignments__route_id"), table_name="vehicle_staff_assignments"
    )
    op.drop_index(
        op.f("ix_vehicle_staff_assignments__staff_id"), table_name="vehicle_staff_assignments"
    )
    op.drop_index(
        op.f("ix_vehicle_staff_assignments__organization_id"),
        table_name="vehicle_staff_assignments",
    )
    op.drop_table("vehicle_staff_assignments")

    op.drop_index("ux_transport_staff__org_employee_ref", table_name="transport_staff")
    op.drop_index("ix_transport_staff__organization_id_status", table_name="transport_staff")
    op.drop_index(op.f("ix_transport_staff__role_id"), table_name="transport_staff")
    op.drop_index(op.f("ix_transport_staff__organization_id"), table_name="transport_staff")
    op.drop_table("transport_staff")

    op.drop_index(
        op.f("ix_transport_staff_roles__organization_id"), table_name="transport_staff_roles"
    )
    op.drop_table("transport_staff_roles")

    sa.Enum(name="staff_assignment_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="transport_staff_status").drop(op.get_bind(), checkfirst=True)
