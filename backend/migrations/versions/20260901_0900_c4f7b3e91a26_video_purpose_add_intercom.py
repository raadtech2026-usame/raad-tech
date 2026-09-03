"""video: ADR-0036 video_purpose enum gains intercom

Revision ID: c4f7b3e91a26
Revises: 3aef3f7c7bb1
Create Date: 2026-09-01 09:00:00.000000

ADR-0036. Widens the `video_purpose` native enum from its original two Database Design §7.4
values (`live`, `playback`) with a third: `intercom`. Purely additive — no column, no table, no
data backfill; every existing `video_sessions` row keeps its current value unchanged. Mirrors
ADR-0032's own `camera_position` widening precedent exactly (`a6682ad19581`).

Downgrade rebuilds the type (Postgres has no `ALTER TYPE ... DROP VALUE`) rather than leaving it
one-way, per this codebase's own "verified zero drift... upgrade -> downgrade -> upgrade round
trip" standard. Any `video_sessions` row already using `intercom` cannot be safely remapped to
`live`/`playback` (unlike `camera_position`'s own safe `other` fallback) — the downgrade instead
refuses if any such row exists, the same "disclosed, not silently lossy" posture this codebase
already applies whenever no safe fallback value exists.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4f7b3e91a26"
down_revision: Union[str, None] = "3aef3f7c7bb1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUE = "intercom"
_ORIGINAL_VALUES = ("live", "playback")


def upgrade() -> None:
    op.execute(f"ALTER TYPE video_purpose ADD VALUE IF NOT EXISTS '{_NEW_VALUE}'")


def downgrade() -> None:
    connection = op.get_bind()
    in_use = connection.execute(
        sa.text("SELECT 1 FROM video_sessions WHERE purpose = 'intercom' LIMIT 1")
    ).first()
    if in_use is not None:
        raise RuntimeError(
            "Cannot downgrade video_purpose: at least one video_sessions row uses 'intercom' "
            "and no safe fallback value exists (unlike camera_position's 'other'). Resolve those "
            "rows manually before downgrading."
        )
    op.execute("ALTER TYPE video_purpose RENAME TO video_purpose_old")
    new_enum = sa.Enum(*_ORIGINAL_VALUES, name="video_purpose")
    new_enum.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE video_sessions ALTER COLUMN purpose TYPE video_purpose "
        "USING purpose::text::video_purpose"
    )
    op.execute("DROP TYPE video_purpose_old")
