"""`billing` -> shared-kernel `audit_entries` bridge (Organization Management phase).

Lives in `core/di/` for the same reason `erp_adapters.py`/`session_cap_adapter.py` do — a
concrete adapter for a port one module's application layer depends on abstractly, kept out of
that module itself so it never has to import past another module's boundary. Unlike those two
files, this one does not cross into *another bounded context* at all: `raad.core.audit.reader`
reads `core.audit.writer.AuditEntryRecord`, a shared-kernel table every module (including
`billing` itself) already writes to directly from its own `UnitOfWork.commit()`. See
`billing.application.ports.PlanHistoryPort`'s own docstring for why this check exists.
"""

from __future__ import annotations

from raad.core.audit.reader import any_entry_references
from raad.core.di.container import Container
from raad.modules.billing.application.ports import BillingUnitOfWork, PlanHistoryPort

_SUBSCRIPTION_PLAN_METADATA_FIELDS = ("plan_id", "old_plan_id", "new_plan_id")


class AuditPlanHistoryAdapter(PlanHistoryPort):
    def __init__(self, container: Container) -> None:
        self._container = container

    async def plan_ever_referenced(self, plan_id: str) -> bool:
        uow: BillingUnitOfWork = self._container.resolve(BillingUnitOfWork)
        async with uow:
            for field_name in _SUBSCRIPTION_PLAN_METADATA_FIELDS:
                if await any_entry_references(
                    uow.session, entity_type="Subscription", field=field_name, value=plan_id
                ):
                    return True
        return False
