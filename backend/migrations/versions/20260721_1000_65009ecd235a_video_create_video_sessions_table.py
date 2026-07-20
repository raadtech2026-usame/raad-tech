"""video: create video_sessions table

Revision ID: 65009ecd235a
Revises: 054a850353e7
Create Date: 2026-07-21 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "65009ecd235a"
down_revision: Union[str, None] = "054a850353e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- video_sessions (Database Design §7.4, "admin-only (D5)") -------------------------
    # No `updated_at`/`created_by`/`updated_by`/`deleted_at`/`row_version` — §7.4 documents
    # exactly its own columns plus "+ created_at" (every session audited), not "+ standard
    # audit cols" the way every other business table in this schema does (see
    # `infra/models.py`'s module docstring).
    op.create_table(
        "video_sessions",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("device_id", sa.CHAR(length=26), nullable=False),
        sa.Column("camera_id", sa.CHAR(length=26), nullable=False),
        sa.Column("purpose", sa.Enum("live", "playback", name="video_purpose"), nullable=False),
        sa.Column("requested_by", sa.CHAR(length=26), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=True),
        sa.Column("window_end", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("requested", "active", "ended", "failed", name="video_session_status"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_video_sessions")),
    )
    op.create_index(
        op.f("ix_video_sessions__organization_id"),
        "video_sessions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_video_sessions__device_id"), "video_sessions", ["device_id"], unique=False
    )
    op.create_index(
        op.f("ix_video_sessions__status"), "video_sessions", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_video_sessions__status"), table_name="video_sessions")
    op.drop_index(op.f("ix_video_sessions__device_id"), table_name="video_sessions")
    op.drop_index(op.f("ix_video_sessions__organization_id"), table_name="video_sessions")
    op.drop_table("video_sessions")

    # PostgreSQL native ENUM types outlive their owning table's DROP (ADR-0002) and must be
    # dropped explicitly, or a later re-upgrade's CREATE TYPE collides with the orphaned one —
    # the same mandatory pattern every prior ENUM-creating revision in this chain follows.
    sa.Enum(name="video_session_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="video_purpose").drop(op.get_bind(), checkfirst=True)
