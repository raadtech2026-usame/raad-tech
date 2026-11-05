"""transport_ops: add composite performance indexes for list and search queries

Revision ID: f7b8c9d0e1a2
Revises: e3a7c5d91b24
Create Date: 2026-11-01 12:00:00.000000

Adds composite indexes on students, parents, and student assignments to accelerate
tenant-scoped name lookups, sorting, and vehicle/route assignment joins.
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

revision: str = "f7b8c9d0e1a2"
down_revision: Union[str, None] = "e3a7c5d91b24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES: tuple[tuple[str, str, list[str], bool], ...] = (
    (
        "students",
        "ix_students__organization_id_full_name",
        ["organization_id", "full_name"],
        False,
    ),
    (
        "parents",
        "ix_parents__organization_id_full_name",
        ["organization_id", "full_name"],
        False,
    ),
    (
        "student_assignments",
        "ix_student_assignments__route_vehicle_status",
        ["route_id", "vehicle_id", "status"],
        False,
    ),
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
        # Existing index matches required definition; accept safely
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


def upgrade() -> None:
    for table_name, index_name, columns, unique in _INDEXES:
        _ensure_index(table_name, index_name, columns, unique=unique)


def downgrade() -> None:
    for table_name, index_name, _, _ in reversed(_INDEXES):
        _drop_index_if_exists(table_name, index_name)

