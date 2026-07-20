"""SQLAlchemy repository implementations for `platform_audit` (Backend LLD §7, §8; Database
Design §8.7/§8.9). Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM <-> domain conversion goes through `mappers.py`.

**`SqlAlchemyAuditEntryRepository` queries `core.audit.writer.AuditEntryRecord` directly** — the
shared-kernel ORM model (ADR-0007), not a module-owned one (`infra/models.py`'s own docstring).
`list_all`'s unrestricted-`TenantRegionScope` caveat carries over unchanged — the same
system-wide, already-flagged `ScopeResolver`-not-yet-wired-into-`list_all` gap every other
module's own `list_all` in this codebase already carries (`billing.infra.repositories`'s own
module docstring gives the identical caveat); not a `platform_audit`-specific regression.

**`SqlAlchemySystemSettingRepository.get` cannot use `SqlAlchemyRepositoryBase.get_by_id`** —
that helper assumes an `.id` column, and `SystemSettingModel`'s primary key is `key`
(`infra/models.py`'s own docstring). A direct `select()` is used instead, mirroring
`SqlAlchemyRouteRepository.get_by_name`'s identical shape for an analogous non-`.id` finder.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.audit.writer import AuditEntryRecord
from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_audit.domain.entities import AuditEntry, SystemSetting
from raad.modules.platform_audit.domain.repositories import (
    AuditEntryRepository,
    SystemSettingRepository,
)
from raad.modules.platform_audit.domain.value_objects import AuditEntryId, SystemSettingKey
from raad.modules.platform_audit.infra.mappers import (
    audit_entry_model_to_domain,
    model_to_system_setting,
    system_setting_to_model,
)
from raad.modules.platform_audit.infra.models import SystemSettingModel


class SqlAlchemyAuditEntryRepository(
    SqlAlchemyRepositoryBase[AuditEntryRecord], AuditEntryRepository
):
    model = AuditEntryRecord

    async def get(self, entry_id: AuditEntryId) -> AuditEntry | None:
        row = await self.get_by_id(str(entry_id))
        return audit_entry_model_to_domain(row) if row is not None else None

    async def list_all(self) -> list[AuditEntry]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [audit_entry_model_to_domain(row) for row in rows]


class SqlAlchemySystemSettingRepository(
    SqlAlchemyRepositoryBase[SystemSettingModel], SystemSettingRepository
):
    model = SystemSettingModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[SystemSetting, SystemSettingModel]] = {}

    async def get(self, key: SystemSettingKey) -> SystemSetting | None:
        statement = select(SystemSettingModel).where(SystemSettingModel.key == str(key))
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, setting: SystemSetting) -> None:
        model = system_setting_to_model(setting)
        super().add(model)
        self._tracked[str(setting.key)] = (setting, model)

    async def list_all(self) -> list[SystemSetting]:
        statement = select(SystemSettingModel)
        result = await self._session.execute(statement)
        return [model_to_system_setting(row) for row in result.scalars().all()]

    def flush_tracked_changes(self) -> None:
        for setting, model in self._tracked.values():
            system_setting_to_model(setting, existing=model)

    def _track(self, row: SystemSettingModel | None) -> SystemSetting | None:
        if row is None:
            return None
        setting = model_to_system_setting(row)
        self._tracked[row.key] = (setting, row)
        return setting


class SqlAlchemyPlatformAuditUnitOfWork(SqlAlchemyUnitOfWork, PlatformAuditUnitOfWork):
    """Concrete `PlatformAuditUnitOfWork` (Backend LLD §8.2/§6.2). Identical shape to
    `billing.infra.repositories.SqlAlchemyBillingUnitOfWork`.
    """

    audit_entries: SqlAlchemyAuditEntryRepository
    system_settings: SqlAlchemySystemSettingRepository

    async def __aenter__(self) -> "SqlAlchemyPlatformAuditUnitOfWork":
        await super().__aenter__()
        self.audit_entries = SqlAlchemyAuditEntryRepository(self.session)
        self.system_settings = SqlAlchemySystemSettingRepository(self.session)
        return self

    async def commit(self) -> None:
        self.system_settings.flush_tracked_changes()
        await super().commit()
