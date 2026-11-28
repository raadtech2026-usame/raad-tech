"""iam: restrict parent and driver default session_cap to 1 device

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-28 11:45:00.000000

Tightens the ADR-0019 `session_cap` system setting for `parent` and `driver` from 3 to 1 so
only one active mobile session is allowed per account (preventing multiple families or devices
from sharing one parent/driver login). Matches `core/di/session_cap_adapter.py`'s updated
fallback defaults (`"parent": 1, "driver": 1`).
"""

import json
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
    system_settings = sa.table(
        "system_settings",
        sa.column("key", sa.VARCHAR()),
        sa.column("value_json", sa.JSON()),
        sa.column("scope", sa.VARCHAR()),
    )
    row = conn.execute(
        sa.select(system_settings.c.value_json).where(
            system_settings.c.key == _SESSION_CAP_KEY
        )
    ).fetchone()
    if row is None:
        return
    raw = row[0]
    current = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(current, dict):
        return
    updated = {**current, "parent": cap, "driver": cap}
    conn.execute(
        system_settings.update()
        .where(system_settings.c.key == _SESSION_CAP_KEY)
        .values(value_json=updated)
    )


def upgrade() -> None:
    _update_parent_driver_cap(1)


def downgrade() -> None:
    _update_parent_driver_cap(3)
