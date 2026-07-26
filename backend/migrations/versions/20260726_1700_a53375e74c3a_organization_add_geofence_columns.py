"""organization add geofence columns

Revision ID: a53375e74c3a
Revises: 8768136a6464
Create Date: 2026-07-26 17:00:00.000000

Adds `latitude`/`longitude`/`geofence_radius_m` to `organizations` (ADR-0014). Phase 2 §22.1
names an "organization geofence" for `VehicleArrivedAtOrganization` evaluation, but the
originally approved Database Design §4.2 gave `organizations` no geographic location column at
all — found while implementing the post-F7 roadmap's item A5 (live geofence evaluation) and
confirmed with the user before adding these columns. All three are nullable: an organization
that hasn't configured its location yet simply has no organization-geofence evaluation performed
for it (never a zero-island fallback) — set together or not at all via
`Organization.set_geofence`, enforced at the domain layer, not the database.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a53375e74c3a"
down_revision: Union[str, None] = "8768136a6464"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # asdecimal=False -> Python float, matching transport_ops.infra.models.StopModel's
    # identical DECIMAL(9,6) lat/long columns exactly.
    op.add_column(
        "organizations",
        sa.Column("latitude", sa.DECIMAL(9, 6, asdecimal=False), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("longitude", sa.DECIMAL(9, 6, asdecimal=False), nullable=True),
    )
    op.add_column(
        "organizations", sa.Column("geofence_radius_m", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("organizations", "geofence_radius_m")
    op.drop_column("organizations", "longitude")
    op.drop_column("organizations", "latitude")
