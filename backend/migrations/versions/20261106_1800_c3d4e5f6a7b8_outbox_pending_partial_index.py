"""events: add partial index on outbox(created_at) for unpublished events

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-06 18:00:00.000000

Remediates audit finding PERF-03:
SqlOutboxPublisher polls periodically for unpublished rows:
    SELECT ... FROM outbox WHERE published_at IS NULL ORDER BY created_at LIMIT :batch_size
Prior to this index, every poll performed a sequential scan across the outbox table.
This partial index indexes only pending rows (WHERE published_at IS NULL), ordering them
by created_at. In production, published events do not bloat this index, reducing pending
lookup latency from sequential scan to index scan.
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_NAME = "outbox"
_INDEX_NAME = "ix_outbox__pending_created_at"
_COLUMNS = ["created_at"]
_WHERE_PREDICATE = "published_at IS NULL"


def _is_offline() -> bool:
    try:
        return context.is_offline_mode()
    except Exception:
        return False


def upgrade() -> None:
    if _is_offline():
        op.create_index(
            _INDEX_NAME,
            _TABLE_NAME,
            _COLUMNS,
            unique=False,
            postgresql_where=sa.text(_WHERE_PREDICATE),
            sqlite_where=sa.text(_WHERE_PREDICATE),
            if_not_exists=True,
        )
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"]: idx for idx in inspector.get_indexes(_TABLE_NAME)}

    if _INDEX_NAME in existing_indexes:
        return

    op.create_index(
        _INDEX_NAME,
        _TABLE_NAME,
        _COLUMNS,
        unique=False,
        postgresql_where=sa.text(_WHERE_PREDICATE),
        sqlite_where=sa.text(_WHERE_PREDICATE),
    )


def downgrade() -> None:
    if _is_offline():
        op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME, if_exists=True)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"]: idx for idx in inspector.get_indexes(_TABLE_NAME)}

    if _INDEX_NAME in existing_indexes:
        op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
