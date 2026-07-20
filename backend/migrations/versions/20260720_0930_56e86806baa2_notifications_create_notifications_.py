"""notifications: create notifications, device_tokens tables

Revision ID: 56e86806baa2
Revises: addb6114f18a
Create Date: 2026-07-20 09:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "56e86806baa2"
down_revision: Union[str, None] = "addb6114f18a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- notifications (Database Design §7.5) - in-app store (D2) -------------------------
    op.create_table(
        "notifications",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("recipient_user_id", sa.CHAR(length=26), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "trip_started",
                "approaching_stop",
                "arrived_org",
                "trip_completed",
                "subscription",
                "system",
                name="notification_type",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.VARCHAR(length=160), nullable=False),
        sa.Column("body", sa.VARCHAR(length=500), nullable=False),
        sa.Column("data_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("trip_id", sa.CHAR(length=26), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        op.f("ix_notifications__organization_id"), "notifications", ["organization_id"], unique=False
    )
    op.create_index(
        "ix_notifications__recipient_created",
        "notifications",
        ["recipient_user_id", "created_at"],
        unique=False,
    )

    # --- device_tokens (Database Design §7.6) - FCM registration --------------------------
    op.create_table(
        "device_tokens",
        sa.Column("user_id", sa.CHAR(length=26), nullable=False),
        sa.Column("fcm_token", sa.VARCHAR(length=255), nullable=False),
        sa.Column(
            "platform",
            sa.Enum("android", "ios", name="device_token_platform"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_tokens")),
        sa.UniqueConstraint("fcm_token", name=op.f("ux_device_tokens__fcm_token")),
    )
    op.create_index(
        op.f("ix_device_tokens__user_id"), "device_tokens", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_device_tokens__user_id"), table_name="device_tokens")
    op.drop_table("device_tokens")

    op.drop_index("ix_notifications__recipient_created", table_name="notifications")
    op.drop_index(op.f("ix_notifications__organization_id"), table_name="notifications")
    op.drop_table("notifications")

    # PostgreSQL native ENUM types outlive their owning table's DROP (ADR-0002) and must be
    # dropped explicitly, or a later re-upgrade's CREATE TYPE collides with the orphaned one.
    # `autogenerate` does not emit this; added by hand (see every prior ENUM-creating revision
    # this chain has, most recently addb6114f18a).
    sa.Enum(name="device_token_platform").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="notification_type").drop(op.get_bind(), checkfirst=True)
