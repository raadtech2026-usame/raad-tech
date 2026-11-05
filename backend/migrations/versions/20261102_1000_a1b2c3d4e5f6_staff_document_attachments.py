"""transport_ops: add staff document file attachment columns

Revision ID: a1b2c3d4e5f6
Revises: f7b8c9d0e1a2
Create Date: 2026-11-02 10:00:00.000000

Adds file_name, file_content_type, and file_data columns to staff_documents
to store national ID, driving license, and certificate attachments.
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f7b8c9d0e1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_NAME = "staff_documents"

_COLUMNS: tuple[tuple[sa.Column, tuple[type, ...] | type, int | None, bool], ...] = (
    (
        sa.Column("file_name", sa.VARCHAR(length=255), nullable=True),
        (sa.String, sa.VARCHAR),
        255,
        True,
    ),
    (
        sa.Column("file_content_type", sa.VARCHAR(length=100), nullable=True),
        (sa.String, sa.VARCHAR),
        100,
        True,
    ),
    (
        sa.Column("file_data", sa.Text(), nullable=True),
        (sa.Text, sa.TEXT),
        None,
        True,
    ),
)


def _ensure_column(
    table_name: str,
    column: sa.Column,
    expected_type_cls: tuple[type, ...] | type,
    expected_length: int | None = None,
    expected_nullable: bool = True,
) -> None:
    column_name = column.name
    if context.is_offline_mode():
        op.add_column(table_name, column, if_not_exists=True)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"]: col for col in inspector.get_columns(table_name)}

    if column_name in existing_columns:
        col = existing_columns[column_name]
        col_type = col.get("type")
        col_nullable = bool(col.get("nullable"))

        if col_nullable != expected_nullable:
            raise RuntimeError(
                f"Existing column '{column_name}' on table '{table_name}' has incompatible nullability: "
                f"nullable={col_nullable} (expected {expected_nullable})"
            )

        if not isinstance(col_type, expected_type_cls):
            raise RuntimeError(
                f"Existing column '{column_name}' on table '{table_name}' has incompatible type: "
                f"{col_type!r} (expected {expected_type_cls})"
            )

        if expected_length is not None:
            actual_len = getattr(col_type, "length", None)
            if actual_len != expected_length:
                raise RuntimeError(
                    f"Existing column '{column_name}' on table '{table_name}' has incompatible length: "
                    f"length={actual_len} (expected {expected_length})"
                )
        return

    op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if context.is_offline_mode():
        op.drop_column(table_name, column_name, if_exists=True)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name in inspector.get_table_names():
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        if column_name in existing_cols:
            op.drop_column(table_name, column_name)


def upgrade() -> None:
    for column, type_cls, length, nullable in _COLUMNS:
        _ensure_column(
            _TABLE_NAME,
            column,
            expected_type_cls=type_cls,
            expected_length=length,
            expected_nullable=nullable,
        )


def downgrade() -> None:
    for column, _, _, _ in reversed(_COLUMNS):
        _drop_column_if_exists(_TABLE_NAME, column.name)

