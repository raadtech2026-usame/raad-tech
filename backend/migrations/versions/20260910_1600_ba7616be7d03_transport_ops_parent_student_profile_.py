"""transport_ops: additive Parent/Student profile fields (Parent & Student Domain Restructure)

Revision ID: ba7616be7d03
Revises: 9f1c3e7a2d64
Create Date: 2026-09-10 16:00:00.000000

2026-09-10 explicit user directive ("Parent & Student Domain Restructure + Parent Payments"):
Student registration/management needs date of birth, gender and notes; Parent registration/
management needs an alternate phone, address, emergency contact, and notes. None of these are
in Database Design §6.2/§6.3 — this migration is purely additive (every column nullable, no
existing column touched, no row rewritten) and does not change either table's primary key,
audit columns, or existing constraints.

**One new PostgreSQL ENUM** (`student_gender`, three values) — explicitly dropped in
`downgrade()` per this repository's own permanent rule (CLAUDE.md, Migration status):
`alembic revision --autogenerate` never emits a `DROP TYPE` itself, and omitting it breaks a
re-upgrade after a downgrade with "type already exists".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ba7616be7d03'
down_revision: Union[str, None] = '9f1c3e7a2d64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Unlike `op.create_table`, `op.add_column` on an *existing* table does not implicitly
    # `CREATE TYPE` for a new PostgreSQL ENUM — it must be created explicitly first, then
    # referenced with `create_type=False` so the column DDL doesn't try to create it again.
    student_gender = sa.Enum('male', 'female', 'other', name='student_gender')
    student_gender.create(op.get_bind(), checkfirst=True)

    op.add_column('students', sa.Column('date_of_birth', sa.Date(), nullable=True))
    op.add_column(
        'students',
        sa.Column('gender', sa.Enum('male', 'female', 'other', name='student_gender', create_type=False), nullable=True),
    )
    op.add_column('students', sa.Column('notes', sa.VARCHAR(length=500), nullable=True))

    op.add_column('parents', sa.Column('alternate_phone', sa.VARCHAR(length=32), nullable=True))
    op.add_column('parents', sa.Column('address', sa.VARCHAR(length=255), nullable=True))
    op.add_column(
        'parents',
        sa.Column('emergency_contact_name', sa.VARCHAR(length=200), nullable=True),
    )
    op.add_column(
        'parents',
        sa.Column('emergency_contact_phone', sa.VARCHAR(length=32), nullable=True),
    )
    op.add_column('parents', sa.Column('notes', sa.VARCHAR(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('parents', 'notes')
    op.drop_column('parents', 'emergency_contact_phone')
    op.drop_column('parents', 'emergency_contact_name')
    op.drop_column('parents', 'address')
    op.drop_column('parents', 'alternate_phone')

    op.drop_column('students', 'notes')
    op.drop_column('students', 'gender')
    op.drop_column('students', 'date_of_birth')

    # `student_gender` is dropped explicitly — see this migration's own module docstring for why.
    op.execute("DROP TYPE IF EXISTS student_gender")
