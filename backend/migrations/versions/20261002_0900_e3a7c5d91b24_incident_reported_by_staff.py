"""transport_ops: incidents record the staff member who reported them (ADR-0061)

Revision ID: e3a7c5d91b24
Revises: d1e5b7a3c9f4
Create Date: 2026-10-02 09:00:00.000000

Phase 5 (mobile self-service). A driver can report an incident from the app and later see the
status of their own reports, which needs to know who reported each one.

One nullable column and its index. Existing incidents keep NULL ("recorded by the office"),
nothing is rewritten and no permission is added: the `/me/incidents` routes are self-scoped.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3a7c5d91b24"
down_revision: Union[str, None] = "d1e5b7a3c9f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "incidents", sa.Column("reported_by_staff_id", sa.CHAR(length=26), nullable=True)
    )
    op.create_foreign_key(
        "fk_incidents__reported_by_staff",
        "incidents",
        "transport_staff",
        ["reported_by_staff_id"],
        ["id"],
    )
    op.create_index(
        "ix_incidents__reported_by_staff_id", "incidents", ["reported_by_staff_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_incidents__reported_by_staff_id", table_name="incidents")
    op.drop_constraint("fk_incidents__reported_by_staff", "incidents", type_="foreignkey")
    op.drop_column("incidents", "reported_by_staff_id")
