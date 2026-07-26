"""organization add approaching_distance_m column

Revision ID: b6f2a19d3e7c
Revises: a53375e74c3a
Create Date: 2026-07-26 18:00:00.000000

Adds `approaching_distance_m` to `organizations` (ADR-0014 amendment). Replaces the temporary
`_APPROACH_RADIUS_MULTIPLIER` stand-in `tracking/events/subscribers.py` previously used
(`stop.geofence_radius_m * 3`) with a real, organization-level configurable value: how far (in
meters) from a stop's own center `APPROACHING_STOP` fires. Unlike `latitude`/`longitude`/
`geofence_radius_m` (also ADR-0014, added in `a53375e74c3a`), this column is **not nullable** —
every organization has some approaching distance, defaulting to 300m (the user's own chosen
default) via a server-side default so existing rows backfill cleanly. Designed for a future
per-stop override (a later phase could add a nullable `stops.approaching_distance_m` that takes
precedence when set) — no schema change needed here to support that later.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b6f2a19d3e7c"
down_revision: Union[str, None] = "a53375e74c3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_APPROACHING_DISTANCE_M = "300"


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "approaching_distance_m",
            sa.Integer(),
            nullable=False,
            server_default=_DEFAULT_APPROACHING_DISTANCE_M,
        ),
    )
    # Server default only exists to backfill existing rows cleanly on this upgrade; the domain
    # layer (Organization.__init__'s own _DEFAULT_APPROACHING_DISTANCE_M) is the actual source of
    # truth for new rows going forward, matching this codebase's "domain-owned invariants"
    # discipline - drop the server default so future inserts always go through the domain layer's
    # own explicit value rather than silently relying on the database's.
    op.alter_column("organizations", "approaching_distance_m", server_default=None)


def downgrade() -> None:
    op.drop_column("organizations", "approaching_distance_m")
