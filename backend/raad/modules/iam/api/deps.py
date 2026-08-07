"""FastAPI dependency wiring for `iam` (Backend LLD §9.2/§16.2). Resolves the DI-container-
bound `IamUnitOfWork` and application services — the only place this module's HTTP layer
touches `core.di`; routers never import the container directly beyond this file, and never
construct a repository or touch SQLAlchemy.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http.deps import get_container, get_scope
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.services import (
    AuthApplicationService,
    MeApplicationService,
    PermissionApplicationService,
    UserApplicationService,
)


def get_iam_uow(container: Container = Depends(get_container)) -> IamUnitOfWork:
    """Resolves a fresh `IamUnitOfWork` per call — **not** entered here. Every
    `UserApplicationService`/`AuthApplicationService` method already manages its own `async
    with uow:` block (Phase 5.2's design, unchanged). Wrapping it again at the dependency
    level (`async with uow: yield uow`, the pattern `interfaces/http/deps.get_uow` uses for
    the generic `UnitOfWork`) would call `__aenter__`/`__aexit__` twice on the same instance:
    the inner block's `__aexit__` closes the session and clears it, so the outer wrapper's own
    `__aexit__` would then raise trying to close an already-closed session. Resolving without
    entering keeps each service call a fully self-contained transaction, as designed.

    **Stays unscoped, deliberately (ADR-0021).** Used by `login`/`refresh` (no `Principal`
    exists yet to resolve a scope from — `Depends(get_scope)` would raise `AuthenticationError`
    outright), `logout`/`change_password`/`get_me` (always the caller's own `user_id`, already
    in-scope under any correct resolution), and `create_user` (targets no existing row, and
    already has its own `_enforce_creation_scope` check). See `get_scoped_iam_uow` below for the
    routes that actually need scoping."""
    return container.resolve(IamUnitOfWork)


def get_scoped_iam_uow(
    container: Container = Depends(get_container),
    scope: TenantRegionScope = Depends(get_scope),
) -> IamUnitOfWork:
    """**ADR-0021**: the scoped counterpart to `get_iam_uow` above, for the genuinely
    admin-target routes — `list_users`/`get_user`/`update_user`/`reset_user_password` — where
    the audit found a real `regional_manager`/`support_staff` scope bypass (any in-scope-role
    caller could list or fetch any organization's users, not just their assigned regions/orgs).
    Sets the caller's resolved `TenantRegionScope` on the UoW before it's entered — every
    repository `SqlAlchemyIamUnitOfWork.__aenter__` constructs picks it up automatically,
    mirroring every other module's identical `get_<module>_uow` fix. Requires
    `Depends(get_principal)` transitively (via `get_scope`), so this dependency must never be
    used on an unauthenticated route."""
    uow = container.resolve(IamUnitOfWork)
    uow.scope = scope
    return uow


def get_user_service(
    container: Container = Depends(get_container),
) -> UserApplicationService:
    return container.resolve(UserApplicationService)


def get_auth_service(
    container: Container = Depends(get_container),
) -> AuthApplicationService:
    return container.resolve(AuthApplicationService)


def get_permission_service(
    container: Container = Depends(get_container),
) -> PermissionApplicationService:
    return container.resolve(PermissionApplicationService)


def get_me_service(
    container: Container = Depends(get_container),
) -> MeApplicationService:
    """ADR-0023."""
    return container.resolve(MeApplicationService)
