"""iam: grant video.intercom.start to founder/org_admin/regional_manager/support_staff (ADR-0036)

Revision ID: d81e6c5f3b47
Revises: c4f7b3e91a26
Create Date: 2026-09-01 09:05:00.000000

ADR-0036 §3. New permission `video.intercom.start`, granted to exactly the same four roles that
hold `video.live.start` today: `founder`, `org_admin`, `regional_manager`, `support_staff`.
**Deliberately not granted to `parent`** — unlike `video.live.start`/`.playback.start`, which
ADR-0026's own later migration (`1470274175d8`) granted parent as a narrow, explicit exception.
No approved document names parent-facing intercom as in scope; this migration does not invent
that surface. `video.sessions.stop` is reused unchanged for stopping an intercom session (already
held by all four roles, plus parent — irrelevant here since parent can never start one) — no new
stop permission is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d81e6c5f3b47"
down_revision: Union[str, None] = "c4f7b3e91a26"
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

_GRANTED_TO = ("founder", "org_admin", "regional_manager", "support_staff")
_PERMISSION = "video.intercom.start"

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    op.bulk_insert(
        _role_permissions_table,
        [{"role": role, "permission": _PERMISSION} for role in _GRANTED_TO],
    )


def downgrade() -> None:
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.role.in_(_GRANTED_TO),
            _role_permissions_table.c.permission == _PERMISSION,
        )
    )
