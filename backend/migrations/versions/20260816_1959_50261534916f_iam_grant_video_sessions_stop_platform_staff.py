"""iam grant video.sessions.stop to regional_manager/support_staff (ADR-0029)

Revision ID: 50261534916f
Revises: 1470274175d8
Create Date: 2026-08-16 19:59:32.660362

ADR-0029: Platform Admin (Founder, Regional Manager, Support Staff) live-video access is
expanded on the web dashboard, aligned to the RBAC/D5 eligibility this backend already
implements (`core.policies.video_access.VideoAccessPolicy._VIDEO_ELIGIBLE_ROLES` has included
`FOUNDER`/`REGIONAL_MANAGER`/`SUPPORT_STAFF`/`ORG_ADMIN` since D5 was first wired up — this
migration closes a real, pre-existing RBAC gap the frontend expansion now surfaces, not a new
authorization decision).

`founder` already holds all three `video.*` permissions (`_ALL_PERMISSIONS`, seed migration
`5437a5d1651b`). `regional_manager`/`support_staff` were granted `video.live.start`/
`.playback.start` by that same seed migration but never `video.sessions.stop` — confirmed live
against the running `role_permissions` table before writing this migration, not assumed. Without
this grant, either role could start a live/playback session but would 403 attempting to stop
their own session via `POST /video/sessions/{id}/stop`.

`org_admin`/`parent`/`founder` are unaffected. `finance_staff`/`driver` hold no `video.*`
permission today and continue to hold none — this migration does not touch either role, matching
ADR-0029's explicit "Finance Staff, Driver, Parent behavior unchanged" scope.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50261534916f'
down_revision: Union[str, None] = '1470274175d8'
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

_GRANTED_TO = ("regional_manager", "support_staff")
_PERMISSION = "video.sessions.stop"

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
