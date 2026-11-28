"""iam: restrict parent and driver default session_cap to 1 device

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-28 11:45:00.000000

Tightens the ADR-0019 `session_cap` system setting for `parent` and `driver` from 3 to 1 so
only one active mobile session is allowed per account (preventing multiple families or devices
from sharing one parent/driver login). Matches `core/di/session_cap_adapter.py`'s updated
fallback defaults (`"parent": 1, "driver": 1`).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SESSION_CAP_KEY = "session_cap"


def _update_parent_driver_cap(cap: int) -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT value_json FROM system_settings WHERE key = :key"),
        {"key": _SESSION_CAP_KEY},
    ).fetchone()
    if row is not None and isinstance(row[0], dict):
        updated = {**row[0], "parent": cap, "driver": cap}
        conn.execute(
            sa.text(
                "UPDATE system_settings SET value_json = :value_json WHERE key = :key"
            ).bindparams(sa.bindparam("value_json", type_=sa.JSON())),
            {"value_json": updated, "key": _SESSION_CAP_KEY},
        )


def upgrade() -> None:
    _update_parent_driver_cap(1)


def downgrade() -> None:
    _update_parent_driver_cap(3)
