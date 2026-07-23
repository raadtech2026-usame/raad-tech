"""organization seed starter regions

Revision ID: 8768136a6464
Revises: 22e94bc4e924
Create Date: 2026-07-23 20:58:49.327636

`POST/GET/PATCH /regions` (`organization/api/routers.py`) already work end to end, but no
migration ever seeded a row and no frontend page ever called `POST /regions` — so `regions`
was permanently empty, and `region_id` being required on `POST /organizations`
(Database Design §4.2) meant Organization creation was fully blocked in any fresh environment
(Device Domain Overhaul architecture review). Seeds a handful of starter regions, labeled as
sample data an admin can rename/add to via the new Regions management page
(`frontend/src/features/organizations/regions/`) — RAAD's target market is East Africa/Middle
East (`RAAD_Phase2_Enterprise_Architecture_v1_2.md`), so starter names are drawn from that
market rather than being arbitrary placeholders.
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from raad.core.ids.generator import generate_ulid

# revision identifiers, used by Alembic.
revision: str = '8768136a6464'
down_revision: Union[str, None] = '22e94bc4e924'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STARTER_REGIONS = [
    {"name": "East Africa", "geographic_scope": "Kenya, Somalia, Ethiopia, Uganda, Tanzania"},
    {"name": "Middle East", "geographic_scope": "UAE, Saudi Arabia, Qatar, Kuwait"},
    {"name": "North Africa", "geographic_scope": "Egypt, Sudan, Libya"},
    {"name": "Southern Africa", "geographic_scope": "South Africa, Zambia, Zimbabwe"},
]

_regions_table = sa.table(
    "regions",
    sa.column("id", sa.CHAR(26)),
    sa.column("name", sa.VARCHAR()),
    sa.column("geographic_scope", sa.VARCHAR()),
    sa.column("status", sa.Enum("active", "inactive", name="region_status")),
    sa.column("created_at", sa.DateTime()),
    sa.column("updated_at", sa.DateTime()),
    sa.column("row_version", sa.Integer()),
)


def upgrade() -> None:
    # Naive UTC, matching the audit-mixin `created_at`/`updated_at` columns' own
    # `DateTime(timezone=False)` type (ADR-0002) — `core.db.mixins.utcnow`'s identical pattern.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.bulk_insert(
        _regions_table,
        [
            {
                "id": generate_ulid(),
                "name": region["name"],
                "geographic_scope": region["geographic_scope"],
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "row_version": 1,
            }
            for region in _STARTER_REGIONS
        ],
    )


def downgrade() -> None:
    op.execute(
        _regions_table.delete().where(
            _regions_table.c.name.in_([region["name"] for region in _STARTER_REGIONS])
        )
    )
