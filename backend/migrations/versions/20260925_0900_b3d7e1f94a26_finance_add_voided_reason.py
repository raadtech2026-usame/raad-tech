"""finance: add voided_reason to income/expense ledgers (school_erp + platform_finance)

Revision ID: b3d7e1f94a26
Revises: f1a4c8b2e6d9
Create Date: 2026-09-25 09:00:00.000000

Finance P0 integrity pass. A void removes an amount from every total and from Profit & Loss,
yet `erp_income`, `erp_expenses`, `platform_income` and `platform_expenses` had no column to say
why — the reason existed only inside the `…Voided` event payload, and the UI sent a fixed
"Voided by school"/"Voided by RAAD" string that explained nothing. `erp_student_payments`
already carries `voided_reason`; these four tables now match it.

Purely additive and nullable: rows voided before this revision keep whatever reason the audit
trail holds (backfilled below) or NULL where none was ever given. The domain now requires a
reason for every *new* void.

**Backfill.** Every void already wrote its reason into `audit_entries.metadata_json` (ADR-0007
writes the event payload verbatim, `action` = the event type, `entity_id` = the aggregate id).
The most recent matching audit row per entity supplies the reason. The stock UI strings are
copied as-is — they are what was recorded; rewriting history is not this migration's job.

`downgrade()` drops the four columns. Reasons captured after upgrade remain in `audit_entries`,
so nothing is lost permanently.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3d7e1f94a26"
down_revision: Union[str, None] = "f1a4c8b2e6d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, audit action written by that aggregate's void event)
_TABLES: tuple[tuple[str, str], ...] = (
    ("erp_income", "school_erp.IncomeVoided"),
    ("erp_expenses", "school_erp.ExpenseVoided"),
    ("platform_income", "platform_finance.IncomeVoided"),
    ("platform_expenses", "platform_finance.ExpenseVoided"),
)


def upgrade() -> None:
    for table, _action in _TABLES:
        op.add_column(table, sa.Column("voided_reason", sa.VARCHAR(255), nullable=True))

    for table, action in _TABLES:
        op.execute(
            sa.text(
                f"""
                UPDATE {table} AS t
                SET voided_reason = LEFT(latest.reason, 255)
                FROM (
                    SELECT DISTINCT ON (entity_id)
                        entity_id, metadata_json ->> 'reason' AS reason
                    FROM audit_entries
                    WHERE action = :action
                    ORDER BY entity_id, created_at DESC
                ) AS latest
                WHERE t.id = latest.entity_id
                  AND t.is_voided
                  AND t.voided_reason IS NULL
                  AND NULLIF(BTRIM(latest.reason), '') IS NOT NULL
                """
            ).bindparams(action=action)
        )


def downgrade() -> None:
    for table, _action in reversed(_TABLES):
        op.drop_column(table, "voided_reason")
