"""Repository interfaces for the `platform_audit` module (Backend LLD §5.1/§7.1/§7.2).
Framework-free — no SQLAlchemy/FastAPI/Pydantic.

**`AuditEntryRepository` is read-only — deliberately no `add`.** This module never creates
`AuditEntry` rows itself (`entities.py`'s own docstring); every row arrives via the shared-kernel
`AuditWriter` from another module's `UnitOfWork.commit()` (ADR-0007). A repository interface with
an `add` method nothing ever calls would misrepresent this module's actual capability — the same
"don't invent a method the aggregate has no real use for" discipline `TransportFeeRepository`'s
own docstring already applies to the analogous "no HTTP route uses this yet" case, taken one step
further here since this repository truly has no write path at all, not just an unexposed one.

`SystemSettingRepository` mirrors every other module's minimal `get`/`add`/`list_all` shape,
with `get` keyed by `SystemSettingKey` rather than a ULID id — the one difference from every
sibling repository interface in this codebase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.modules.platform_audit.domain.entities import AuditEntry, SystemSetting
from raad.modules.platform_audit.domain.value_objects import AuditEntryId, SystemSettingKey


class AuditEntryRepository(ABC):
    @abstractmethod
    async def get(self, entry_id: AuditEntryId) -> AuditEntry | None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[AuditEntry]:
        """Backs `ListAuditEntriesQuery` (`GET /admin/audit`, API Contracts §4.8: "audit log
        (scoped, read-only)"). Tenant/region scoping is applied at the infra layer via
        `SqlAlchemyRepositoryBase.list_scoped` — the identical mandatory-filter mechanism every
        other module's own `list_all` already uses, including the Founder-unrestricted case."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[AuditEntry]:
        """Backs `GET /admin/audit`'s paginated/filtered/sorted contract (API Contracts §7/§8).
        Still read-only, like every other method on this repository (module docstring) — a
        `list_page` read method doesn't conflict with the "deliberately no `add`" rule above."""
        raise NotImplementedError


class SystemSettingRepository(ABC):
    @abstractmethod
    async def get(self, key: SystemSettingKey) -> SystemSetting | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, setting: SystemSetting) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[SystemSetting]:
        """Backs `ListSystemSettingsQuery` (`GET /admin/settings`, API Contracts §4.8)."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[SystemSetting]:
        """Backs `GET /admin/settings`'s paginated/filtered/sorted contract (API Contracts
        §7/§8). Callers must never pass an empty `sort` here — `SystemSettingModel` has no `id`
        column (`infra/models.py`'s own docstring), so `SqlAlchemyRepositoryBase.list_page`'s
        empty-sort fallback (`.order_by(self.model.id.asc())`) would raise `AttributeError`;
        `PlatformAuditApplicationService.list_system_settings` is the one place that guards
        this, defaulting to `[SortSpec(field="key")]`."""
        raise NotImplementedError
