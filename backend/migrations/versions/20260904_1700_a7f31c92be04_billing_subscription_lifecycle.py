"""billing: subscription lifecycle states, timestamps and RBAC realignment (ADR-0039)

Revision ID: a7f31c92be04
Revises: d81e6c5f3b47
Create Date: 2026-09-04 17:00:00.000000

ADR-0039. Three independent changes, deliberately in one migration because they are one
behavioural change and must not be half-applied — a deployment with the new enum values but the
old RBAC grants would leave `parent` able to read the SaaS invoices of an organization it can
now also observe being suspended.

1. **`subscription_status` gains `past_due` and `grace_period`** (ADR-0039 §1). `past_due` is
   automatic (the clock produced it); `grace_period` is granted (a platform admin chose it).
   See `billing.domain.value_objects.SubscriptionStatus` for why both exist.

2. **`subscriptions` gains five lifecycle timestamps** — `past_due_since`,
   `grace_period_ends_at`, `suspended_at`, `cancelled_at`, `expired_at`. All nullable: a
   subscription that has never gone delinquent legitimately has none of them, and every existing
   row is therefore correct with `NULL` — no backfill needed, no data loss possible.
   `grace_period_ends_at` is indexed because the lifecycle job filters on it every tick.

3. **`parent`'s stale SaaS-billing grants are revoked** (ADR-0039 §7). `billing.invoices.list`,
   `billing.payments.create` and `billing.subscriptions.list` were seeded for `parent` by the
   original RBAC migration (`5437a5d1651b`, 2026-07-21) under the parent-pays billing model.
   **ADR-0016 (`f4a1c9e7b302`, 2026-07-28) removed that model's schema but never revoked these
   grants**, leaving a live exposure: a parent could enumerate *RAAD's own SaaS invoices to
   their school* and initiate payments against them. Revoked here.

   `billing.plans.list` is deliberately **retained** for `parent`: the plan catalogue is
   platform-level, non-tenant, non-financial reference data already granted to five other roles.
   Parent access to *school* (ERP) invoices is a separate future concern under `school_erp.*`
   and, per ADR-0038, must be per-student-ownership scoped rather than a role-wide grant.

4. **New `billing.subscriptions.manage`** — gates the platform-admin suspend / reactivate /
   extend-grace routes (requirement 39G/39S). Granted to `founder` and `finance_staff` only.
   Deliberately **not** `org_admin`: a tenant must never be able to lift its own suspension.
   Deliberately a new permission rather than reusing `billing.subscriptions.list`, which
   `org_admin` holds — reuse would have handed exactly that self-reactivation power to the
   tenant.

**Downgrade honesty.** PostgreSQL supports `ALTER TYPE ... ADD VALUE` but has **no
`DROP VALUE`**, so `downgrade()` cannot remove `past_due`/`grace_period` from the enum type.
Removing them would require recreating the type and rewriting every dependent column — far more
destructive than the forward change. `downgrade()` therefore drops the columns and restores the
grants (fully reversible) and leaves the two labels in place (inert if unused). This is stated
here rather than left for a future reader to discover mid-rollback.

**Downgrade data caveat:** any subscription sitting in `past_due`/`grace_period` at downgrade
time would hold a status the old code does not understand. `downgrade()` moves those rows to
`suspended` first — the nearest pre-ADR-0039 state that preserves the "not in good standing"
meaning, chosen over `active` (which would silently restore access to a delinquent tenant).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7f31c92be04"
down_revision: Union[str, None] = "d81e6c5f3b47"
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

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)

#: ADR-0039 §7 — stale parent grants left behind by ADR-0016's own migration.
_PARENT_REVOKED_PERMISSIONS = (
    "billing.invoices.list",
    "billing.payments.create",
    "billing.subscriptions.list",
)

_MANAGE_PERMISSION = "billing.subscriptions.manage"
_MANAGE_GRANTED_TO = ("founder", "finance_staff")

_NEW_ENUM_VALUES = ("past_due", "grace_period")

_LIFECYCLE_COLUMNS = (
    "past_due_since",
    "grace_period_ends_at",
    "suspended_at",
    "cancelled_at",
    "expired_at",
)


def upgrade() -> None:
    # --- 1. enum values -----------------------------------------------------------------------
    # `IF NOT EXISTS` makes this re-runnable against a database where a previous partial attempt
    # already added one of them — `ADD VALUE` is not transactional-rollback-safe on every
    # PostgreSQL version, so the idempotent form is the safer spelling.
    for value in _NEW_ENUM_VALUES:
        op.execute(
            f"ALTER TYPE subscription_status ADD VALUE IF NOT EXISTS '{value}'"
        )

    # --- 2. lifecycle timestamp columns -------------------------------------------------------
    for column in _LIFECYCLE_COLUMNS:
        op.add_column(
            "subscriptions",
            sa.Column(column, sa.DateTime(timezone=False), nullable=True),
        )
    op.create_index(
        "ix_subscriptions__grace_period_ends_at",
        "subscriptions",
        ["grace_period_ends_at"],
    )

    # --- 3. revoke parent's stale SaaS-billing grants ------------------------------------------
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.role == "parent",
            _role_permissions_table.c.permission.in_(_PARENT_REVOKED_PERMISSIONS),
        )
    )

    # --- 4. platform-admin subscription management --------------------------------------------
    op.bulk_insert(
        _role_permissions_table,
        [
            {"role": role, "permission": _MANAGE_PERMISSION}
            for role in _MANAGE_GRANTED_TO
        ],
    )


def downgrade() -> None:
    # --- 4. drop the management permission ----------------------------------------------------
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.permission == _MANAGE_PERMISSION,
        )
    )

    # --- 3. restore parent's original (pre-ADR-0039) grants -----------------------------------
    # Restores the state this migration found, not a state we think is correct — a downgrade's
    # job is to undo, not to improve.
    op.bulk_insert(
        _role_permissions_table,
        [
            {"role": "parent", "permission": permission}
            for permission in _PARENT_REVOKED_PERMISSIONS
        ],
    )

    # --- 2. move rows off the values the old code cannot read, then drop the columns -----------
    # See this migration's own docstring: `suspended` is the nearest pre-ADR-0039 state that
    # preserves "not in good standing". Mapping these to `active` would silently hand a
    # delinquent tenant its access back as a side effect of a rollback.
    op.execute(
        "UPDATE subscriptions SET status = 'suspended' "
        "WHERE status IN ('past_due', 'grace_period')"
    )
    op.drop_index("ix_subscriptions__grace_period_ends_at", table_name="subscriptions")
    for column in reversed(_LIFECYCLE_COLUMNS):
        op.drop_column("subscriptions", column)

    # --- 1. enum values are intentionally NOT removed ------------------------------------------
    # PostgreSQL has no `ALTER TYPE ... DROP VALUE`. Removing `past_due`/`grace_period` would
    # mean recreating `subscription_status` and rewriting every dependent column — strictly more
    # destructive than the forward change. They are left in place, unused and inert.
