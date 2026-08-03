"""iam: add account lockout columns

Revision ID: d4fbe03f2b94
Revises: 7eb581884c39
Create Date: 2026-08-03 12:00:00.000000

Priority 1 Item 3 (`PROJECT_STATUS.md`) — account lockout. Adds `failed_login_attempts`
(counts consecutive failed logins since the last success or the last lockout window's expiry)
and `locked_until` (a plain expiry timestamp; `User.is_locked` compares it to "now" rather than
needing a separate write to clear it once the window passes) to `users`. Purely additive, both
columns backed by a server-side default so existing rows need no separate backfill — same shape
`22e94bc4e924`'s/`a43c7de2fad5`'s own add-column migrations already establish.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4fbe03f2b94"
down_revision: Union[str, None] = "7eb581884c39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users", sa.Column("locked_until", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
