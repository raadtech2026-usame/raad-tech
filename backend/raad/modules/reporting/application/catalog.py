"""The report catalogue (ADR-0040 §6).

**`reporting` renders rows; it does not know what they mean.** Each owning module registers a
`ReportDefinition` whose `build` callable returns a `ReportTable`, and this module draws it. That
is what lets both report catalogues grow — platform and organization — without `reporting` ever
importing `school_erp`, `platform_finance` or `billing` domain types, and without those modules
learning anything about PDF layout.

**This also closes, narrowly, the `ReportDefinition` gap CLAUDE.md has flagged since Reporting
was built.** That gap was specifically "no `report_definitions` *table* in the schema authority,
so `ReportType` stays an opaque string". Nothing here adds a table: the catalogue is
**code-resident**, keyed by the same opaque `definition_key` string `report_runs` already stores.
A report is a piece of software, not a row — and inventing a schema for one would still be
inventing schema the authority does not define.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable, Protocol

from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.reporting.application.report_table import ReportTable


@dataclass(frozen=True)
class ReportRequest:
    """Everything a report builder is allowed to know about the caller's request.

    `organization_id` is resolved by the API layer from the principal (an Org Admin's own, a
    platform role's explicit choice) — a builder never reads it from raw query input, so a
    builder cannot be tricked into rendering another tenant's data.

    `scope` is the caller's **already-resolved** `TenantRegionScope`, produced by the same
    `ScopeResolver` (ADR-0005) every ordinary route uses, and handed down so a builder can put it
    straight onto its Unit of Work. Deriving it from `principal.org_id` instead — as the first
    version of this did — silently loses a Regional Manager's assigned-regions restriction and a
    Support Staff's assigned-organizations restriction, because neither principal carries an
    `org_id` at all: both would have resolved to "unrestricted" and read every school's ledger.
    """

    principal: Principal
    organization_id: str | None = None
    start: date | None = None
    end: date | None = None
    period: str | None = None
    vehicle_id: str | None = None
    scope: TenantRegionScope | None = None


class ReportBuilder(Protocol):
    async def __call__(self, request: ReportRequest) -> ReportTable: ...


@dataclass(frozen=True)
class ReportDefinition:
    """One entry in the catalogue.

    `roles` is enforced in **two** places, and both are load-bearing. `ReportCatalog.list_for`
    uses it to decide what a caller is *offered*; `ReportExportService.export` re-checks it before
    building anything, because a caller can name a `definition_key` that was never offered to
    them. The listing filter alone would leave `platform.invoices` — whose builder spans every
    tenant on purpose — reachable by any role holding the single shared
    `reporting.reports.request` permission.

    It is not a substitute for tenant scoping: each builder still reads through repositories
    carrying the caller's own `TenantRegionScope` (ADR-0021). `roles` draws the line between
    *which report*, the scope draws the line between *whose rows*.
    """

    key: str
    title: str
    description: str
    scope: str  # "platform" | "organization"
    build: ReportBuilder
    roles: tuple[Role, ...] = ()
    #: Which optional inputs this report actually uses, so the UI can show only the relevant
    #: filters rather than every filter for every report.
    accepts: tuple[str, ...] = field(default_factory=tuple)


class ReportCatalog:
    """In-memory registry, populated once at composition-root time.

    Deliberately not a database table — see this module's own docstring.
    """

    def __init__(self) -> None:
        self._definitions: dict[str, ReportDefinition] = {}

    def register(self, definition: ReportDefinition) -> None:
        if definition.key in self._definitions:
            raise ValueError(f"Duplicate report definition key: {definition.key}")
        self._definitions[definition.key] = definition

    def get(self, key: str) -> ReportDefinition | None:
        return self._definitions.get(key)

    def list_for(self, principal: Principal, *, scope: str | None = None) -> list[ReportDefinition]:
        return [
            definition
            for definition in self._definitions.values()
            if (scope is None or definition.scope == scope)
            and (not definition.roles or principal.role in definition.roles)
        ]

    def __len__(self) -> int:
        return len(self._definitions)
