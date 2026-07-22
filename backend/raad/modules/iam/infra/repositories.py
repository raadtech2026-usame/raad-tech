"""SQLAlchemy repository implementations for `iam` (Backend LLD §7, §8; Database Design
§4.3/§4.5). Compose `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` — repositories never
return an ORM model, only the domain aggregates `modules/iam/domain/repositories.py`
declares (§7.1's "aggregate-in/aggregate-out" rule).

**The identity-map problem this file solves:** because `get()`/`get_by_email()`/etc. return a
plain domain object (not the tracked ORM row), a handler that does
`user = await uow.users.get(id); user.activate(...)` mutates only that detached domain
object — SQLAlchemy's session never sees the change, since it only dirty-tracks its own
`UserModel` instances. Per Phase 5.2, the application layer never re-calls `add()` after such
a mutation (that's reserved for genuinely new aggregates), so something in *this* layer must
bridge the gap. Each repository keeps a `{id: (domain_object, orm_row)}` map of everything it
has returned or added, and `flush_tracked_changes()` re-projects every tracked domain object
onto its row via the mapper immediately before commit — called by
`SqlAlchemyIamUnitOfWork.commit()`, below.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import FilterField, SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.principal import Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.domain.entities import RefreshToken, User
from raad.modules.iam.domain.repositories import (
    RefreshTokenRepository,
    RolePermissionRepository,
    UserRepository,
)
from raad.modules.iam.domain.value_objects import (
    Email,
    PhoneNumber,
    RefreshTokenId,
    UserId,
)
from raad.modules.iam.infra.mappers import (
    model_to_refresh_token,
    model_to_user,
    refresh_token_to_model,
    user_to_model,
)
from raad.modules.iam.infra.models import (
    RefreshTokenModel,
    RolePermissionModel,
    UserModel,
)


class SqlAlchemyUserRepository(SqlAlchemyRepositoryBase[UserModel], UserRepository):
    """`get_by_email`/`get_by_phone` intentionally search *all* organizations — `users.email`/
    `users.phone` are globally unique by design (Database Design §4.3), not per-tenant, since
    login must resolve a principal before any tenant/region scope is known. Tenant/region
    scoping (Phase 2 §17.4) has no call site yet in this phase's use-cases (none list/page
    users); it applies once a scoped listing use-case exists, via `list_scoped` on the shared
    base class.
    """

    model = UserModel

    #: Whitelist for `GET /users` (§8) — limited to columns already on `UserResponse`.
    #: `role`'s `transform` lower-cases the incoming filter value before comparison, since
    #: `UserResponse.role`/`Role.value` (what a client sees and would naturally filter by) is
    #: upper-case while the stored column is lower-case (`iam.infra.mappers`'s own docstring).
    filterable_fields = {
        "organization_id": FilterField(column="organization_id"),
        "role": FilterField(column="role", transform=str.lower),
        "status": FilterField(column="status"),
    }
    sortable_fields = {
        "full_name": "full_name",
        "status": "status",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }
    searchable_fields = ("full_name", "email")

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[User, UserModel]] = {}

    async def get(self, user_id: UserId) -> User | None:
        row = await self.get_by_id(str(user_id))
        return self._track(row)

    async def get_by_email(self, email: Email) -> User | None:
        statement = select(UserModel).where(
            UserModel.email == str(email), UserModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    async def get_by_phone(self, phone: PhoneNumber) -> User | None:
        statement = select(UserModel).where(
            UserModel.phone == str(phone), UserModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, user: User) -> None:
        model = user_to_model(user)
        super().add(model)
        self._tracked[str(user.id)] = (user, model)

    async def list_all(self) -> list[User]:
        """Unrestricted `TenantRegionScope` — not yet scope-filtered, the same system-wide,
        already-flagged gap every other module's own `list_all()` carries."""
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [self._track(row) for row in rows]  # type: ignore[misc]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[User]:
        """Same unrestricted-scope posture as `list_all` above."""
        raw_page = await super().list_page(
            TenantRegionScope(organization_ids=None),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

    def flush_tracked_changes(self) -> None:
        for user, model in self._tracked.values():
            user_to_model(user, existing=model)

    def _track(self, row: UserModel | None) -> User | None:
        if row is None:
            return None
        user = model_to_user(row)
        self._tracked[row.id] = (user, row)
        return user


class SqlAlchemyRefreshTokenRepository(
    SqlAlchemyRepositoryBase[RefreshTokenModel], RefreshTokenRepository
):
    model = RefreshTokenModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[RefreshToken, RefreshTokenModel]] = {}

    async def get(self, token_id: RefreshTokenId) -> RefreshToken | None:
        row = await self.get_by_id(str(token_id))
        return self._track(row)

    async def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        statement = select(RefreshTokenModel).where(
            RefreshTokenModel.token_hash == token_hash
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, refresh_token: RefreshToken) -> None:
        model = refresh_token_to_model(refresh_token)
        super().add(model)
        self._tracked[str(refresh_token.id)] = (refresh_token, model)

    def flush_tracked_changes(self) -> None:
        for token, model in self._tracked.values():
            refresh_token_to_model(token, existing=model)

    def _track(self, row: RefreshTokenModel | None) -> RefreshToken | None:
        if row is None:
            return None
        token = model_to_refresh_token(row)
        self._tracked[row.id] = (token, row)
        return token


class SqlAlchemyRolePermissionRepository(RolePermissionRepository):
    """No identity-map/`flush_tracked_changes` needed — `role_permissions` has no domain
    entity to track (`domain/repositories.py`'s own docstring); `grant`/`revoke` write directly
    via the session, matching `core.db.repository.SqlAlchemyRepositoryBase.add`'s identical
    "session.add is enough" shape for a row with no in-place-mutation lifecycle.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_permissions_for_role(self, role: Role) -> frozenset[str]:
        statement = select(RolePermissionModel.permission).where(
            RolePermissionModel.role == role.value.lower()
        )
        result = await self._session.execute(statement)
        return frozenset(result.scalars().all())

    async def grant(self, role: Role, permission: str) -> None:
        existing = await self._session.get(
            RolePermissionModel, (role.value.lower(), permission)
        )
        if existing is not None:
            return
        self._session.add(
            RolePermissionModel(role=role.value.lower(), permission=permission)
        )

    async def revoke(self, role: Role, permission: str) -> None:
        existing = await self._session.get(
            RolePermissionModel, (role.value.lower(), permission)
        )
        if existing is not None:
            await self._session.delete(existing)


class SqlAlchemyIamUnitOfWork(SqlAlchemyUnitOfWork, IamUnitOfWork):
    """Concrete `IamUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `iam`'s three repositories
    once the session is open, and re-syncs every tracked aggregate's in-place mutations onto
    its ORM row (`flush_tracked_changes`, above) immediately before delegating to
    `SqlAlchemyUnitOfWork.commit()` — which still owns the actual outbox-write + session-commit
    behavior, preserved exactly (§8.3), via `super().commit()`.
    """

    users: SqlAlchemyUserRepository
    refresh_tokens: SqlAlchemyRefreshTokenRepository
    role_permissions: SqlAlchemyRolePermissionRepository

    async def __aenter__(self) -> "SqlAlchemyIamUnitOfWork":
        await super().__aenter__()
        self.users = SqlAlchemyUserRepository(self.session)
        self.refresh_tokens = SqlAlchemyRefreshTokenRepository(self.session)
        self.role_permissions = SqlAlchemyRolePermissionRepository(self.session)
        return self

    async def commit(self) -> None:
        self.users.flush_tracked_changes()
        self.refresh_tokens.flush_tracked_changes()
        await super().commit()
