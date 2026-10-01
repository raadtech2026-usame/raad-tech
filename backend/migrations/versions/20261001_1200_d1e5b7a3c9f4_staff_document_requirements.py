"""transport_ops: document-type requirements (ADR-0058)

Revision ID: d1e5b7a3c9f4
Revises: c9f2a4e6b1d7
Create Date: 2026-10-01 12:00:00.000000

Phase 4 of the transport-management roadmap ("Documents & Compliance expansion").

`staff_document_types` gains `required_for` (`none`/`drivers`/`all_staff`) and `enforcement`
(`warn`/`block`). Both are NOT NULL with server defaults `none` and `warn`, so every existing
type keeps exactly its current meaning: nothing is required until an Org Admin says so.

No table is created, no row is rewritten and no permission is added: reading compliance reuses
`transport_ops.staff_documents.list` and changing a requirement reuses `.manage`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e5b7a3c9f4"
down_revision: Union[str, None] = "c9f2a4e6b1d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REQUIREMENT = ("none", "drivers", "all_staff")
_ENFORCEMENT = ("warn", "block")


def upgrade() -> None:
    # `op.add_column` on an existing table does not create the enum type itself (unlike
    # `op.create_table`), so the types are created first.
    bind = op.get_bind()
    sa.Enum(*_REQUIREMENT, name="staff_document_requirement").create(bind, checkfirst=True)
    sa.Enum(*_ENFORCEMENT, name="staff_document_enforcement").create(bind, checkfirst=True)
    op.add_column(
        "staff_document_types",
        sa.Column(
            "required_for",
            sa.Enum(*_REQUIREMENT, name="staff_document_requirement", create_type=False),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "staff_document_types",
        sa.Column(
            "enforcement",
            sa.Enum(*_ENFORCEMENT, name="staff_document_enforcement", create_type=False),
            nullable=False,
            server_default="warn",
        ),
    )


def downgrade() -> None:
    op.drop_column("staff_document_types", "enforcement")
    op.drop_column("staff_document_types", "required_for")
    bind = op.get_bind()
    sa.Enum(name="staff_document_enforcement").drop(bind, checkfirst=True)
    sa.Enum(name="staff_document_requirement").drop(bind, checkfirst=True)
