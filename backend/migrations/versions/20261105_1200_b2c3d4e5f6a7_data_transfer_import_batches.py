"""data_transfer: create import_batches table and seed RBAC grants

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-05 12:00:00.000000

Creates the `import_batches` table for persisting bulk data import jobs,
author metadata, file statistics, row metrics, and audit history.
Seeds RBAC permissions for centralized platform administrators (Founder,
Regional Manager, Support Staff) while explicitly withholding import
execution rights from Org Admin.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
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

_NEW_PERMISSIONS = (
    "data_transfer.templates.read",
    "data_transfer.import.execute",
    "data_transfer.import.history",
)

# Founder: full platform-wide data transfer capabilities
# Regional Manager: data transfer within authorized regional scope
# Support Staff: data transfer within authorized operational assignments
# Finance Staff: template reading only (for fee/finance schedules)
# Org Admin: NONE (centralized enterprise onboarding managed by RAAD-TECH only)
# Driver / Parent: NONE
_GRANTS: tuple[tuple[str, str], ...] = (
    ("founder", "data_transfer.templates.read"),
    ("founder", "data_transfer.import.execute"),
    ("founder", "data_transfer.import.history"),
    ("regional_manager", "data_transfer.templates.read"),
    ("regional_manager", "data_transfer.import.execute"),
    ("regional_manager", "data_transfer.import.history"),
    ("support_staff", "data_transfer.templates.read"),
    ("support_staff", "data_transfer.import.execute"),
    ("support_staff", "data_transfer.import.history"),
    ("finance_staff", "data_transfer.templates.read"),
)

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    # 1. Create import_batches table
    op.create_table(
        "import_batches",
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("actor_user_id", sa.CHAR(length=26), nullable=False),
        sa.Column("resource_type", sa.VARCHAR(length=64), nullable=False),
        sa.Column("status", sa.VARCHAR(length=32), nullable=False),
        sa.Column("original_filename", sa.VARCHAR(length=255), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_strategy", sa.VARCHAR(length=32), nullable=True),
        sa.Column("error_report_available", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
    )

    op.create_index(
        "ix_import_batches__organization_id",
        "import_batches",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_import_batches__actor_user_id",
        "import_batches",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_import_batches__created_at",
        "import_batches",
        ["created_at"],
        unique=False,
    )

    # 2. Seed RBAC grants
    op.bulk_insert(
        _role_permissions_table,
        [{"role": role, "permission": permission} for role, permission in _GRANTS],
    )


def downgrade() -> None:
    # 1. Revoke RBAC grants
    for role, permission in _GRANTS:
        op.execute(
            _role_permissions_table.delete().where(
                _role_permissions_table.c.role == role,
                _role_permissions_table.c.permission == permission,
            )
        )

    # 2. Drop import_batches table
    op.drop_index("ix_import_batches__created_at", table_name="import_batches")
    op.drop_index("ix_import_batches__actor_user_id", table_name="import_batches")
    op.drop_index("ix_import_batches__organization_id", table_name="import_batches")
    op.drop_table("import_batches")
