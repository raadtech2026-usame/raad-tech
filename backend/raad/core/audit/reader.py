"""Shared-kernel read helper for `audit_entries` (ADR-0007).

`audit_entries` is `core`-owned, not owned by `platform_audit` — that module exposes only its
*read side* over HTTP (`GET /admin/audit`); the *write* side (`AuditWriter`, this package's
sibling module) is already imported directly by every other module's own `UnitOfWork.commit()`.
Reading it directly from another module's own infra/adapter layer is therefore not the
cross-module-table read `.claude/rules/backend.md` #3 forbids — it is the identical shared-kernel
access pattern every module's write path already uses, just for a read.

First consumer: `core/di/billing_audit_adapter.py`'s `AuditPlanHistoryAdapter`, closing a real
gap `Subscription.change_plan` opened in `billing.delete_plan`'s own safety check (see
`billing.application.ports.PlanHistoryPort`'s docstring for the full story).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.audit.writer import AuditEntryRecord


async def any_entry_references(
    session: AsyncSession, *, entity_type: str, field: str, value: str
) -> bool:
    """True if any `audit_entries` row for `entity_type` has `metadata_json[field] == value` —
    e.g. "was this plan id ever the `plan_id`/`old_plan_id`/`new_plan_id` of a `Subscription`
    event". `.op("->>")` is PostgreSQL's own JSON text-extraction operator, which works
    identically for the plain `JSON` column type `AuditEntryRecord.metadata_json` actually uses
    and for `JSONB` alike — verified directly against this column's real data before relying on
    it here."""
    statement = (
        select(AuditEntryRecord.id)
        .where(
            AuditEntryRecord.entity_type == entity_type,
            AuditEntryRecord.metadata_json.op("->>")(field) == value,
        )
        .limit(1)
    )
    result = await session.execute(statement)
    return result.scalar() is not None
