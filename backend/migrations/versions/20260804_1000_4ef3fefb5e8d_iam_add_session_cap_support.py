"""iam: add refresh_tokens.device_label, seed session_cap SystemSetting

Revision ID: 4ef3fefb5e8d
Revises: f3d8b1a4e6c2
Create Date: 2026-08-04 10:00:00.000000

ADR-0019 (Account-Sharing Protection — concurrent session cap). Two purely additive changes:

1. `refresh_tokens.device_label` — a short, human-readable derivation of `user_agent`
   (`core.security.user_agent.parse_device_label`), shown back to the user via
   `GET /auth/sessions`. `user_agent`/`ip_address` already exist on this table (added before
   this ADR, previously dead — nothing populated them); this is the one genuinely new column.

2. Seeds exactly one `system_settings` row (`key="session_cap"`) rather than one row per role —
   `SystemSettingKey`'s own enforced max length is 26 characters (`domain/value_objects.py`),
   which a per-role key like `session_cap.regional_manager` cannot fit; `value_json` is already
   typed as an arbitrary dict, so one row holding `{role: max_sessions}` needs no schema change
   and lets every role be edited in a single `PATCH /admin/settings` call. Values: tighter for
   `parent`/`driver` (the literal one-account-shared-with-many-parents scenario this ADR names),
   looser for RAAD-staff/`org_admin` roles that legitimately use multiple devices/browsers —
   matches `core/di/session_cap_adapter.py`'s own hardcoded fallback defaults exactly, so a
   fresh deployment's *configured* and *fallback-if-missing* values agree from the start.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4ef3fefb5e8d"
down_revision: Union[str, None] = "f3d8b1a4e6c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SESSION_CAP_KEY = "session_cap"
_SESSION_CAP_VALUE = {
    "parent": 3,
    "driver": 3,
    "org_admin": 10,
    "founder": 20,
    "regional_manager": 20,
    "support_staff": 20,
    "finance_staff": 20,
}


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("device_label", sa.VARCHAR(length=64), nullable=True),
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
                "key": _SESSION_CAP_KEY,
                "value_json": _SESSION_CAP_VALUE,
                "scope": "platform",
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM system_settings WHERE key = :key").bindparams(
            key=_SESSION_CAP_KEY
        )
    )
    op.drop_column("refresh_tokens", "device_label")
