"""transport_ops/iam: ADR-0026 parent video access authorization

Revision ID: 1470274175d8
Revises: a3580db8138a
Create Date: 2026-08-12 10:00:00.000000

ADR-0026 (Parent Video Access Authorization). Two purely additive changes, bundled into one
migration since both belong to the same ADR (mirroring `b288c2e44aa5`'s own precedent of
bundling a column add + a permission-grant insert for a single ADR):

1. `parents.has_video_live_access`/`has_video_playback_access` — off by default for every
   existing and future row (`NOT NULL DEFAULT false`, both) — a parent never has any video
   reachability until an org_admin explicitly grants it via `PATCH /parents/{id}/video-access`.
   Two independent booleans, not one combined flag: live and playback are separately grantable
   (ADR-0026 §1/§3).

2. Grants a new `transport_ops.parents.grant_video_access` permission (backing the new
   `PATCH /parents/{id}/video-access` route) to `org_admin` and `founder` only — deliberately not
   reused from `transport_ops.parents.update` (least privilege, ADR-0026 §2) and deliberately not
   granted to `regional_manager`/`support_staff`/`finance_staff` (the user's own instruction
   scopes this to "organization administrators"). `founder` is granted explicitly, not inherited,
   for the same reason `b288c2e44aa5`'s own `admin.platform_stats.read` grant explicitly included
   `founder` despite `5437a5d1651b`'s `_ALL_PERMISSIONS` list nominally covering every
   permission — that list is frozen at the point that original migration ran and does not retroactively
   include any permission string invented afterward, so every later ADR that adds a brand-new
   permission must re-grant it to `founder` explicitly if platform-wide superuser access is
   intended (confirmed intended here: Founder already manages Organizations end to end).

   Also grants Parent the three existing video RBAC permissions (`video.live.start`/
   `video.playback.start`/`video.sessions.stop`) — RBAC layer 2 only, "may attempt," not "may
   succeed": `interfaces/http/policy_guards`'s new parent-specific D5 chain (ADR-0026 §3) is what
   actually decides whether a given request succeeds, the same "role can attempt, policy decides
   per-instance" split CR-1 already established for `tracking.vehicles.read_latest`.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1470274175d8"
down_revision: Union[str, None] = "a3580db8138a"
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

_GRANT_VIDEO_ACCESS_PERMISSION = "transport_ops.parents.grant_video_access"
_PARENT_VIDEO_PERMISSIONS = ("video.live.start", "video.playback.start", "video.sessions.stop")

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)

_NEW_GRANTS = [
    {"role": "org_admin", "permission": _GRANT_VIDEO_ACCESS_PERMISSION},
    {"role": "founder", "permission": _GRANT_VIDEO_ACCESS_PERMISSION},
] + [{"role": "parent", "permission": permission} for permission in _PARENT_VIDEO_PERMISSIONS]


def upgrade() -> None:
    op.add_column(
        "parents",
        sa.Column(
            "has_video_live_access", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "parents",
        sa.Column(
            "has_video_playback_access", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.bulk_insert(_role_permissions_table, _NEW_GRANTS)


def downgrade() -> None:
    for grant in _NEW_GRANTS:
        op.execute(
            _role_permissions_table.delete().where(
                sa.and_(
                    _role_permissions_table.c.role == grant["role"],
                    _role_permissions_table.c.permission == grant["permission"],
                )
            )
        )
    op.drop_column("parents", "has_video_playback_access")
    op.drop_column("parents", "has_video_live_access")
