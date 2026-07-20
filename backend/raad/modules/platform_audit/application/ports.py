"""Outbound ports the `platform_audit` application layer depends on (Backend LLD §4.2).
`UnitOfWork` is the existing core abstraction (`core.db.unit_of_work`), extended here with this
module's two repositories, mirroring `billing.application.ports.BillingUnitOfWork` exactly.
"""

from __future__ import annotations

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.platform_audit.domain.repositories import (
    AuditEntryRepository,
    SystemSettingRepository,
)


class PlatformAuditUnitOfWork(UnitOfWork):
    """Bundles this module's two repositories onto one transaction boundary, mirroring
    `BillingUnitOfWork`'s identical shape. The concrete implementation is
    `infra.repositories.SqlAlchemyPlatformAuditUnitOfWork`.
    """

    audit_entries: AuditEntryRepository
    system_settings: SystemSettingRepository
