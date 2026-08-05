"""billing: payment provider architecture (ADR-0022)

Revision ID: a3580db8138a
Revises: b288c2e44aa5
Create Date: 2026-08-06 10:00:00.000000

Three purely additive changes, bundled per this project's own "one revision per phase" chain
discipline (mirrors `4ef3fefb5e8d`'s identical column-plus-seed-row shape):

1. `payments.failure_reason` (nullable `VARCHAR(255)`) — records a provider-supplied decline
   message on a failed payment; previously discarded entirely.
2. `billing.payments.list` — a new permission (no list route existed for `Payment` at all
   before this ADR), granted to `founder`/`finance_staff`/`org_admin`, mirroring
   `billing.subscriptions.list`'s existing grant set exactly (not `regional_manager`/
   `support_staff`, who hold only `billing.plans.list` in the seeded matrix).
3. One `system_settings` row (`key="billing_payment_provider"`, `scope="platform"`,
   `value_json={"provider": "stripe"}`) — the *non-secret* half of ADR-0022's provider
   configuration (which provider is active), read via the already-existing
   `GET /admin/settings` route so the frontend can decide what payment UI to render. The
   actual Stripe secret key/webhook secret are environment-only
   (`RAAD_PAYMENT__PROVIDER_CREDENTIALS`) and never appear in this table — ADR-0022's own
   explicit rejection of storing secrets in `SystemSetting`, since `org_admin` holds
   `admin.settings.read`/`.update` too and would otherwise be able to read/tamper with a
   platform-wide secret.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a3580db8138a"
down_revision: Union[str, None] = "b288c2e44aa5"
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
_ROLES_GRANTED = ("founder", "finance_staff", "org_admin")
_PERMISSION = "billing.payments.list"

_PROVIDER_SETTING_KEY = "billing_payment_provider"
_PROVIDER_SETTING_VALUE = {"provider": "stripe"}


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("failure_reason", sa.VARCHAR(length=255), nullable=True),
    )

    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
        sa.column("permission", sa.VARCHAR()),
    )
    op.bulk_insert(
        role_permissions_table,
        [{"role": role, "permission": _PERMISSION} for role in _ROLES_GRANTED],
    )

    system_settings_table = sa.table(
        "system_settings",
        sa.column("key", sa.VARCHAR()),
        sa.column("value_json", sa.JSON()),
        sa.column("scope", sa.VARCHAR()),
    )
    op.bulk_insert(
        system_settings_table,
        [
            {
                "key": _PROVIDER_SETTING_KEY,
                "value_json": _PROVIDER_SETTING_VALUE,
                "scope": "platform",
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM system_settings WHERE key = :key").bindparams(
            key=_PROVIDER_SETTING_KEY
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission = :permission "
            "AND role = ANY(:roles)"
        ).bindparams(permission=_PERMISSION, roles=list(_ROLES_GRANTED))
    )
    op.drop_column("payments", "failure_reason")
