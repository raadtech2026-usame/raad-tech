"""transport_ops: add staff document file attachment columns

Revision ID: a1b2c3d4e5f6
Revises: f7b8c9d0e1a2
Create Date: 2026-11-02 10:00:00.000000

Adds file_name, file_content_type, and file_data columns to staff_documents
to store national ID, driving license, and certificate attachments.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f7b8c9d0e1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("staff_documents", sa.Column("file_name", sa.VARCHAR(length=255), nullable=True))
    op.add_column("staff_documents", sa.Column("file_content_type", sa.VARCHAR(length=100), nullable=True))
    op.add_column("staff_documents", sa.Column("file_data", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("staff_documents", "file_data")
    op.drop_column("staff_documents", "file_content_type")
    op.drop_column("staff_documents", "file_name")
