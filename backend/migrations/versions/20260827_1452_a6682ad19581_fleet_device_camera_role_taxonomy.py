"""fleet_device: ADR-0032 camera role/capability model generalization

Revision ID: a6682ad19581
Revises: 7d3a9c1e5b42
Create Date: 2026-08-27 14:52:00.000000

ADR-0032. Widens the `camera_position` native enum from its original three Database Design
§5.3 values (`in_cabin`, `road_facing`, `other`) with five directional/role values a discovered
channel can now be assigned to: `front`, `rear`, `left`, `right`, `driver_facing`. Purely
additive — no column, no table, no data backfill; every existing `cameras` row keeps its current
value unchanged (all four rows on the bench device are `other` at the time of writing).

`driver_facing` joins `in_cabin` in `CameraPosition.is_cabin_facing` (domain value object) — the
new single source of truth for D5's "never exposed to parents" exclusion, which this same ADR
also found was never actually enforced anywhere in the authorization chain despite being
documented since the original camera table migration (see `interfaces/http/policy_guards.py`'s
`resolve_d5_decision` for the fix — a code change, not a schema one, not part of this migration).

Downgrade rebuilds the type (Postgres has no `ALTER TYPE ... DROP VALUE`) rather than leaving it
one-way, per this codebase's own "verified zero drift... upgrade -> downgrade -> upgrade round
trip" standard. Any camera row already using one of the five new values is remapped to `other`
first — a genuine, disclosed downgrade data-loss point (ADR-0030's own discovery default is
`other` too, so this is the same fallback the system already uses elsewhere, not a new one).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a6682ad19581"
down_revision: Union[str, None] = "7d3a9c1e5b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = ("front", "rear", "left", "right", "driver_facing")
_ORIGINAL_VALUES = ("in_cabin", "road_facing", "other")


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE camera_position ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    op.execute(
        "UPDATE cameras SET position = 'other' WHERE position IN "
        "('front', 'rear', 'left', 'right', 'driver_facing')"
    )
    op.execute("ALTER TYPE camera_position RENAME TO camera_position_old")
    new_enum = sa.Enum(*_ORIGINAL_VALUES, name="camera_position")
    new_enum.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE cameras ALTER COLUMN position TYPE camera_position "
        "USING position::text::camera_position"
    )
    op.execute("DROP TYPE camera_position_old")
