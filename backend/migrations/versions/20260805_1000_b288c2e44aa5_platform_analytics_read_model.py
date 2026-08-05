"""fleet_device/iam/iam: ADR-0020 platform analytics read model

Revision ID: b288c2e44aa5
Revises: 4ef3fefb5e8d
Create Date: 2026-08-05 10:00:00.000000

ADR-0020 (Platform Analytics Read Model). Three purely additive changes, bundled into one
migration since all three belong to the same ADR (matching `4ef3fefb5e8d`'s own precedent of
bundling a column add + a seed insert for a single ADR):

1. `devices.is_online` — closes the "Online/Offline Devices" gap (ADR-0020 §3). Extends the
   *existing* `DeviceConnectivityProcessor` (`fleet_device/events/subscribers.py`), which
   already consumes `DeviceOnline`/`DeviceOffline` and populates `devices.last_seen_at` — no new
   event consumer was needed (`PROJECT_STATUS.md` Known Issue #9 had already flagged the ADR's
   own §3 text as stale on this point). `NOT NULL DEFAULT false` — never claim a device is
   online until a real `DeviceOnline` event says so.

2. `ix_users__last_login_at` — backs the new MAU ("Monthly Active Users") query
   (`SqlAlchemyUserRepository.count_last_login_after`). This column had no index before this
   migration; without one, that query would be an unindexed full-table scan on every dashboard
   load — acceptable for a low-frequency admin read, but cheap enough to fix properly while this
   migration already touches this ADR's scope.

3. Grants a new `admin.platform_stats.read` permission (backing `GET /admin/platform-stats`) to
   `founder`/`regional_manager`/`support_staff`/`finance_staff` — a **new dedicated permission**,
   not a reuse of `admin.audit.read`: confirmed by reading the seeded matrix
   (`5437a5d1651b`) that `finance_staff` does not hold `admin.audit.read` today, contradicting
   ADR-0020's own claim that all four roles already hold the `GET /admin/audit` grant. The ADR
   itself anticipates this exact fallback ("plus a new dedicated permission if the existing
   grant proves too coarse") — Finance Staff's own KPIs (revenue, billing status) make this the
   right call, not a workaround. New additive grant migration, mirroring `a1c9e4f2b871`'s own
   precedent of never mutating an already-applied seed migration in place.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b288c2e44aa5"
down_revision: Union[str, None] = "4ef3fefb5e8d"
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

_PLATFORM_STATS_PERMISSION = "admin.platform_stats.read"
_GRANTED_ROLES = ("founder", "regional_manager", "support_staff", "finance_staff")

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_users__last_login_at", "users", ["last_login_at"])
    op.bulk_insert(
        _role_permissions_table,
        [
            {"role": role, "permission": _PLATFORM_STATS_PERMISSION}
            for role in _GRANTED_ROLES
        ],
    )


def downgrade() -> None:
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.permission == _PLATFORM_STATS_PERMISSION
        )
    )
    op.drop_index("ix_users__last_login_at", table_name="users")
    op.drop_column("devices", "is_online")
