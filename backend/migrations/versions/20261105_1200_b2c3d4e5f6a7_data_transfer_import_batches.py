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
from alembic import context, op
from sqlalchemy.dialects.postgresql import insert as pg_insert

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

_INDEXES: tuple[tuple[str, str, list[str], bool], ...] = (
    (
        "import_batches",
        "ix_import_batches__organization_id",
        ["organization_id"],
        False,
    ),
    (
        "import_batches",
        "ix_import_batches__actor_user_id",
        ["actor_user_id"],
        False,
    ),
    (
        "import_batches",
        "ix_import_batches__created_at",
        ["created_at"],
        False,
    ),
)

_EXPECTED_COLUMNS: dict[str, tuple[tuple[type, ...] | type, bool]] = {
    "id": ((sa.CHAR, sa.String), False),
    "organization_id": ((sa.CHAR, sa.String), False),
    "actor_user_id": ((sa.CHAR, sa.String), False),
    "resource_type": ((sa.VARCHAR, sa.String), False),
    "status": ((sa.VARCHAR, sa.String), False),
    "original_filename": ((sa.VARCHAR, sa.String), True),
    "file_size_bytes": (sa.BigInteger, True),
    "total_rows": (sa.Integer, False),
    "created_count": (sa.Integer, False),
    "updated_count": (sa.Integer, False),
    "skipped_count": (sa.Integer, False),
    "failed_count": (sa.Integer, False),
    "conflict_strategy": ((sa.VARCHAR, sa.String), True),
    "error_report_available": (sa.Boolean, False),
    "committed_at": (sa.DateTime, True),
    "created_at": (sa.DateTime, False),
    "updated_at": (sa.DateTime, False),
}


def _ensure_import_batches_table() -> None:
    if context.is_offline_mode():
        _create_import_batches_table()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "import_batches" not in inspector.get_table_names():
        _create_import_batches_table()
        return

    # Verify existing table definition
    existing_cols = {col["name"]: col for col in inspector.get_columns("import_batches")}
    for col_name, (expected_type_cls, expected_nullable) in _EXPECTED_COLUMNS.items():
        if col_name not in existing_cols:
            raise RuntimeError(
                f"Existing 'import_batches' table is missing required column: '{col_name}'"
            )
        col = existing_cols[col_name]
        col_nullable = bool(col.get("nullable"))
        col_type = col.get("type")
        if col_nullable != expected_nullable:
            raise RuntimeError(
                f"Existing 'import_batches' column '{col_name}' has incompatible nullability: "
                f"nullable={col_nullable} (expected {expected_nullable})"
            )
        if not isinstance(col_type, expected_type_cls):
            raise RuntimeError(
                f"Existing 'import_batches' column '{col_name}' has incompatible type: "
                f"{col_type!r} (expected {expected_type_cls})"
            )


def _create_import_batches_table() -> None:
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


def _ensure_index(
    table_name: str,
    index_name: str,
    expected_columns: list[str],
    unique: bool = False,
) -> None:
    if context.is_offline_mode():
        op.create_index(index_name, table_name, expected_columns, unique=unique, if_not_exists=True)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"]: idx for idx in inspector.get_indexes(table_name)}

    if index_name in existing_indexes:
        idx = existing_indexes[index_name]
        col_names = list(idx.get("column_names") or [])
        is_unique = bool(idx.get("unique"))
        if col_names != expected_columns or is_unique != unique:
            raise RuntimeError(
                f"Existing index '{index_name}' on table '{table_name}' has incompatible definition: "
                f"columns={col_names} (expected {expected_columns}), unique={is_unique} (expected {unique})"
            )
        return

    op.create_index(index_name, table_name, expected_columns, unique=unique)


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    if context.is_offline_mode():
        op.drop_index(index_name, table_name=table_name, if_exists=True)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name in inspector.get_table_names():
        existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=table_name)


def _seed_rbac_grants() -> None:
    if context.is_offline_mode():
        op.bulk_insert(
            _role_permissions_table,
            [{"role": role, "permission": permission} for role, permission in _GRANTS],
        )
        return

    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_role_permissions_table.c.role, _role_permissions_table.c.permission).where(
            _role_permissions_table.c.permission.in_(_NEW_PERMISSIONS)
        )
    ).fetchall()
    existing_grants = {(r[0], r[1]) for r in rows}

    missing_grants = [
        {"role": role, "permission": permission}
        for role, permission in _GRANTS
        if (role, permission) not in existing_grants
    ]

    if missing_grants:
        if bind.dialect.name == "postgresql":
            stmt = pg_insert(_role_permissions_table).values(missing_grants).on_conflict_do_nothing(
                index_elements=["role", "permission"]
            )
            op.execute(stmt)
        else:
            op.bulk_insert(_role_permissions_table, missing_grants)

    # Post-check: verify all expected grants are present
    verified_rows = bind.execute(
        sa.select(_role_permissions_table.c.role, _role_permissions_table.c.permission).where(
            _role_permissions_table.c.permission.in_(_NEW_PERMISSIONS)
        )
    ).fetchall()
    verified_grants = {(r[0], r[1]) for r in verified_rows}
    missing_after_seed = set(_GRANTS) - verified_grants
    if missing_after_seed:
        raise RuntimeError(
            f"Failed to seed required RBAC permissions: missing {missing_after_seed}"
        )


def upgrade() -> None:
    # 1. Create import_batches table if missing, or verify if existing
    _ensure_import_batches_table()

    # 2. Ensure indexes
    for table_name, index_name, columns, unique in _INDEXES:
        _ensure_index(table_name, index_name, columns, unique=unique)

    # 3. Seed RBAC grants idempotently
    _seed_rbac_grants()


def downgrade() -> None:
    # 1. Revoke RBAC grants added by this migration
    if not context.is_offline_mode():
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        if "role_permissions" in inspector.get_table_names():
            for role, permission in _GRANTS:
                op.execute(
                    _role_permissions_table.delete().where(
                        sa.and_(
                            _role_permissions_table.c.role == role,
                            _role_permissions_table.c.permission == permission,
                        )
                    )
                )
    else:
        for role, permission in _GRANTS:
            op.execute(
                _role_permissions_table.delete().where(
                    sa.and_(
                        _role_permissions_table.c.role == role,
                        _role_permissions_table.c.permission == permission,
                    )
                )
            )

    # 2. Drop indexes on import_batches if they exist
    for table_name, index_name, _, _ in reversed(_INDEXES):
        _drop_index_if_exists(table_name, index_name)

    # 3. Drop import_batches table if exists
    if context.is_offline_mode():
        op.drop_table("import_batches")
    else:
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        if "import_batches" in inspector.get_table_names():
            op.drop_table("import_batches")

