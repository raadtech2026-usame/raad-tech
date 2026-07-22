"""Repository base interfaces and SQLAlchemy infrastructure (Backend LLD §7.2).

Generic, aggregate-agnostic contracts. Each module defines its own aggregate-specific
repository interface in `modules/<context>/domain/repositories.py` by extending
`TenantScopedRepository` for its aggregate (e.g. a future `TripRepository(
TenantScopedRepository[Trip, TripId])`) — no aggregate-specific repository is defined here,
since no module's domain layer is implemented in this phase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Generic, Sequence, TypeVar

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.base import Base
from raad.core.errors.exceptions import ValidationError
from raad.core.pagination import (
    CursorPage,
    CursorPageRequest,
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
    decode_cursor,
    encode_cursor,
)
from raad.core.tenancy.scope import TenantRegionScope

TAggregate = TypeVar("TAggregate")
TId = TypeVar("TId")


class Specification(ABC):
    """Marker base for query specifications passed to `TenantScopedRepository.list`."""


class Page(Generic[TAggregate]):
    """Minimal page envelope for repository list results. Finalized alongside
    `core/pagination` (not implemented in this phase)."""

    def __init__(self, items: list[TAggregate], total: int) -> None:
        self.items = items
        self.total = total


class Repository(ABC, Generic[TAggregate, TId]):
    """Persistence-ignorant collection abstraction for one aggregate root (§7.1). Persistence
    of changes is flushed by the Unit of Work, not the repository."""

    @abstractmethod
    async def get(self, id: TId) -> TAggregate | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, aggregate: TAggregate) -> None:
        raise NotImplementedError


class TenantScopedRepository(Repository[TAggregate, TId], ABC):
    """Every query is implicitly filtered by the active tenant/region scope
    (`TenantRegionScope`, core/tenancy) — this is where isolation is enforced in exactly one
    place (§7.3, Phase 2 §12.3)."""

    @abstractmethod
    async def list(
        self, spec: Specification, page: int, page_size: int
    ) -> Page[TAggregate]:
        raise NotImplementedError


TModel = TypeVar("TModel", bound=Base)


@dataclass(frozen=True)
class FilterField:
    """One entry in a concrete repository's `filterable_fields` whitelist (§8: "Allowed fields
    are whitelisted per resource" — never an arbitrary client-supplied column name). `value_type`
    controls how the raw query-string value is coerced before binding: unlike SQLite, asyncpg
    requires the bound Python value's type to already match the column type, so a bare string
    compared against e.g. a `DateTime`/`Integer` column raises `asyncpg.exceptions.DataError`
    rather than being silently cast. `transform`, when given, normalizes the raw string before
    coercion — e.g. `iam`'s `role` column is stored lower-case while `UserResponse.role` (and
    thus what a client would naturally filter by) is upper-case (`core.tenancy.principal.Role`'s
    own casing, `iam.infra.mappers`'s module docstring) — a plain per-resource whitelist entry,
    not a generic feature every field needs."""

    column: str
    value_type: type = str
    transform: Callable[[str], str] | None = None


def _coerce_filter_value(raw: str, spec: FilterField) -> object:
    if spec.transform is not None:
        raw = spec.transform(raw)
    if spec.value_type is bool:
        return raw.strip().lower() in {"1", "true", "yes"}
    if spec.value_type is int:
        return int(raw)
    if spec.value_type is float:
        return float(raw)
    if spec.value_type is datetime:
        return datetime.fromisoformat(raw)
    if spec.value_type is date:
        return date.fromisoformat(raw)
    return raw


class SqlAlchemyRepositoryBase(Generic[TModel]):
    """Infra-layer helper wrapping common query mechanics (session-bound CRUD, mandatory
    tenant/region scope filtering, soft-delete-aware reads) for a single ORM *model* class —
    not an aggregate. A module's concrete repository (`infra/repositories.py`) composes this
    (rather than implementing `Repository`/`TenantScopedRepository` by hand) and adds its own
    row<->aggregate mapping on top, per §7.1's "aggregate-in/aggregate-out" rule — this class
    only ever returns ORM rows, since it has no knowledge of any module's domain types.

    Set `model` in the subclass, e.g. `class DeviceModelRepo(SqlAlchemyRepositoryBase[Device
    ORM]): model = DeviceORM`.
    """

    model: type[TModel]

    #: Per-resource whitelists (§8) — empty by default, so a concrete repository must opt in
    #: field-by-field rather than accidentally exposing every column to client-controlled
    #: filter/sort input. Keys are the public query-string field name; values name the actual
    #: ORM attribute (identical in almost every case, distinct when the wire name and column
    #: name differ).
    filterable_fields: dict[str, FilterField] = {}
    sortable_fields: dict[str, str] = {}
    searchable_fields: tuple[str, ...] = ()

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, id_: str, *, include_deleted: bool = False
    ) -> TModel | None:
        statement = select(self.model).where(self.model.id == id_)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            statement = statement.where(self.model.deleted_at.is_(None))
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    def add(self, instance: TModel) -> None:
        self._session.add(instance)

    async def list_scoped(
        self, scope: TenantRegionScope, *, include_deleted: bool = False
    ) -> Sequence[TModel]:
        """Applies the mandatory tenant/region scope filter (Phase 2 §17.4) to a model with an
        `organization_id` column — the single place tenant isolation is enforced at the
        persistence layer (Backend LLD §7.3), rather than trusting every call site to
        remember it."""
        statement = select(self.model)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            statement = statement.where(self.model.deleted_at.is_(None))
        if not scope.is_unrestricted and hasattr(self.model, "organization_id"):
            statement = statement.where(
                self.model.organization_id.in_(scope.organization_ids)
            )
        result = await self._session.execute(statement)
        return result.scalars().all()

    def _apply_filters(self, statement, filters: Sequence[FilterCondition]):
        for condition in filters:
            spec = self.filterable_fields.get(condition.field)
            if spec is None:
                raise ValidationError(
                    f"Field {condition.field!r} is not filterable on this resource.",
                    details={"field": condition.field},
                )
            column = getattr(self.model, spec.column)
            if condition.op == "in":
                values = [
                    _coerce_filter_value(part.strip(), spec)
                    for part in condition.value.split(",")
                    if part.strip()
                ]
                statement = statement.where(column.in_(values))
                continue
            value = _coerce_filter_value(condition.value, spec)
            if condition.op == "eq":
                statement = statement.where(column == value)
            elif condition.op == "gte":
                statement = statement.where(column >= value)
            elif condition.op == "lte":
                statement = statement.where(column <= value)
            elif condition.op == "gt":
                statement = statement.where(column > value)
            elif condition.op == "lt":
                statement = statement.where(column < value)
        return statement

    def _apply_sort(self, statement, sort: Sequence[SortSpec]):
        order_columns = []
        for spec in sort:
            column_name = self.sortable_fields.get(spec.field)
            if column_name is None:
                raise ValidationError(
                    f"Field {spec.field!r} is not sortable on this resource.",
                    details={"field": spec.field},
                )
            column = getattr(self.model, column_name)
            order_columns.append(column.desc() if spec.descending else column.asc())
        return statement.order_by(*order_columns) if order_columns else statement

    def _apply_search(self, statement, search: str | None):
        if not search or not self.searchable_fields:
            return statement
        term = f"%{search}%"
        conditions = [
            getattr(self.model, field_name).ilike(term)
            for field_name in self.searchable_fields
        ]
        return statement.where(or_(*conditions))

    async def list_page(
        self,
        scope: TenantRegionScope,
        page_request: OffsetPageRequest,
        *,
        sort: Sequence[SortSpec] = (),
        filters: Sequence[FilterCondition] = (),
        search: str | None = None,
        include_deleted: bool = False,
    ) -> OffsetPage[TModel]:
        """Offset pagination (§7: "admin tables where total counts matter"). Total is computed
        from the same filtered/scoped predicate the page query itself uses, so `total` always
        matches what repeated pagination would eventually enumerate."""
        base = select(self.model)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            base = base.where(self.model.deleted_at.is_(None))
        if not scope.is_unrestricted and hasattr(self.model, "organization_id"):
            base = base.where(self.model.organization_id.in_(scope.organization_ids))
        base = self._apply_filters(base, filters)
        base = self._apply_search(base, search)

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        statement = self._apply_sort(base, sort)
        if not sort:
            statement = statement.order_by(self.model.id.asc())
        statement = statement.offset(page_request.offset).limit(page_request.page_size)
        result = await self._session.execute(statement)
        items = list(result.scalars().all())
        return OffsetPage(
            data=items,
            total=total,
            page=page_request.page,
            page_size=page_request.page_size,
        )

    async def list_cursor_page(
        self,
        scope: TenantRegionScope,
        cursor_request: CursorPageRequest,
        *,
        cursor_column: str,
        descending: bool = True,
        filters: Sequence[FilterCondition] = (),
        include_deleted: bool = False,
    ) -> CursorPage[TModel]:
        """Cursor pagination (§7: "stable under inserts, efficient on time-ordered data like
        positions/notifications") over a single, fixed `(cursor_column, id)` keyset — not a
        generic any-field cursor system, since both documented call sites
        (`vehicle_positions.event_time`, `notifications.created_at`) paginate over one already-
        indexed timestamp column each. `cursor_column` must name a `datetime`-typed column."""
        column = getattr(self.model, cursor_column)
        base = select(self.model)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            base = base.where(self.model.deleted_at.is_(None))
        if not scope.is_unrestricted and hasattr(self.model, "organization_id"):
            base = base.where(self.model.organization_id.in_(scope.organization_ids))
        base = self._apply_filters(base, filters)

        if cursor_request.cursor is not None:
            raw_value, row_id = decode_cursor(cursor_request.cursor)
            cursor_value = datetime.fromisoformat(raw_value)
            if descending:
                base = base.where(
                    or_(
                        column < cursor_value,
                        and_(column == cursor_value, self.model.id < row_id),
                    )
                )
            else:
                base = base.where(
                    or_(
                        column > cursor_value,
                        and_(column == cursor_value, self.model.id > row_id),
                    )
                )

        order = (
            (column.desc(), self.model.id.desc())
            if descending
            else (column.asc(), self.model.id.asc())
        )
        statement = base.order_by(*order).limit(cursor_request.limit + 1)
        result = await self._session.execute(statement)
        rows = list(result.scalars().all())

        has_more = len(rows) > cursor_request.limit
        page_rows = rows[: cursor_request.limit]

        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            last_value = getattr(last, cursor_column)
            next_cursor = encode_cursor(last_value.isoformat(), str(last.id))

        return CursorPage(
            data=page_rows,
            limit=cursor_request.limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )
