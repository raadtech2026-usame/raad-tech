"""tracking: add vehicle_positions.is_gps_valid (RAAD Live Tracking wrong-location fix)

Revision ID: e7c3a95d1f42
Revises: a9c73e5f0b8d
Create Date: 2026-09-11 16:00:00.000000

Root cause of the RAAD Live Tracking map intermittently showing the procured hardware's factory
test location (Shenzhen, China) instead of the vehicle's real position (Mogadishu): neither
device-plane vendor adapter (`services/device-gateway/src/vendors/jt808/`,
`services/device-gateway/src/vendors/lsz/`) propagated the wire-level GPS fix-validity signal —
JT/T 808's `status` DWORD bit 1 ("positioned") and the LSZ protocol's 'A'/'V' positioning-status
flag were both parsed and then discarded — so a position report sent while the device had no
genuine GPS fix was published, cached, and displayed identically to a live one. For this
vendor's hardware, a fix-invalid report commonly carries a stale, cached factory coordinate from
Shenzhen rather than a zeroed one.

`vehicle_positions.is_gps_valid` is the durable half of the fix: every position is still
recorded (never dropped, per this codebase's "never invent/never silently hide a vehicle
location" posture), but now flagged so a reader can tell a genuine live fix apart from a
fix-invalid report. `services/device-gateway`'s own `RedisLatestPositionWriter` (a separate,
already-deployed component, no migration involved) additionally now skips updating
`vehicle:{id}:last` for any fix-invalid report, so `GET /tracking/vehicles/{id}/latest` and the
Fleet Overview snapshot never surface one as "the current position" either.

Purely additive: `NOT NULL DEFAULT true` backfills every pre-existing row as valid — this
codebase has no reason to doubt GPS history recorded before this column existed, and a bulk
`UPDATE` across a 380,510+ row (and growing) partitioned table would be pure cost for no benefit
here. `vehicle_positions` is `PARTITION BY RANGE (event_time)` as of `c8b4d17e9f30` — adding a
column to the partitioned parent applies it to every partition (including the `DEFAULT` one)
automatically; PostgreSQL requires no per-partition DDL for this.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7c3a95d1f42"
down_revision: Union[str, None] = "a9c73e5f0b8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vehicle_positions",
        sa.Column("is_gps_valid", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("vehicle_positions", "is_gps_valid")
