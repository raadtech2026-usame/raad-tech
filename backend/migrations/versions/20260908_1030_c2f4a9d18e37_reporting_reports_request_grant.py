"""iam: grant reporting.reports.request, the permission the export routes actually check

Revision ID: c2f4a9d18e37
Revises: b5c81f3d47a9
Create Date: 2026-09-08 10:30:00.000000

**Closes a real, live defect, not a design change.** ADR-0040 §6 added
`GET /reports/catalog` and `GET /reports/{definition_key}/export`, both gated on
`require_permission(Permission("reporting.reports.request"))` — a permission string **no
migration in this chain ever granted to any role**. Verified against the running database before
writing this: `select role, permission from role_permissions where permission like 'reporting%'`
returns only `reporting.reports.create` and `reporting.reports.read`. Every call to either route
therefore returned `403 FORBIDDEN` for every role including Founder, which made the entire
Reports feature — its catalogue, its eleven definitions and both renderers — unreachable in
production while every test still passed (no test exercised a live RBAC check on those routes).

**Why a new permission rather than reusing the two that exist.** `reporting.reports.create`
means "queue an async `ReportRun`" and `reporting.reports.read` means "read a run I requested";
`parent` holds the latter. Synchronous export is a third capability — it renders and returns real
data immediately — and folding it into `.read` would hand every parent a live export route.
`.claude/rules/security.md` #1 (least privilege, nothing inherited implicitly) is why it stays
its own permission with its own grant list.

**Who gets it.** The five roles that own a report definition in
`core/di/report_definitions.py`'s catalogue: `founder`, `regional_manager`, `support_staff`,
`finance_staff` (platform reports) and `org_admin` (organization reports). Not `parent`, not
`driver` — neither has a definition addressed to it, and neither should reach a rendering route.

**This grant alone is not the gate, and must not be mistaken for one.** Because one permission
covers every definition, it cannot distinguish "may export their own school's billing" from "may
export RAAD's own operating costs". `ReportExportService.export` re-checks each definition's own
`roles` tuple before building anything (added in the same change as this migration) — without
that check this grant would let an Org Admin export `platform.invoices`, whose builder sets
`organization_ids=None` on purpose, and `platform.profit_and_loss`, which reads
`platform_finance` — a module with no `organization_id` column for any scope filter to match
(ADR-0040 §1). The two changes are one fix and belong together.

New additive migration, never an edit to the already-applied `b5c81f3d47a9` — the same posture
every prior grant migration in this chain takes.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2f4a9d18e37"
down_revision: Union[str, None] = "b5c81f3d47a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE_VALUES = (
    "founder",
    "regional_manager",
    "support_staff",
    "finance_staff",
    "org_admin",
    "driver",
    "parent",
)

_PERMISSION = "reporting.reports.request"

_ROLES: tuple[str, ...] = (
    "founder",
    "regional_manager",
    "support_staff",
    "finance_staff",
    "org_admin",
)

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    op.bulk_insert(
        _role_permissions_table,
        [{"role": role, "permission": _PERMISSION} for role in _ROLES],
    )


def downgrade() -> None:
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.permission == _PERMISSION
        )
    )
