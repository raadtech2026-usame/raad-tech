"""Shared FastAPI dependencies (Backend LLD §9.2, §16.2): auth, tenant/region scope, UoW,
pagination.

`get_principal` reads the `Principal` that `SecurityContextMiddleware`
(`interfaces/http/middleware.py`) already verified and attached to `request.state.principal`
— it only *enforces* that one was found, keeping JWT verification itself out of the dependency
layer. `get_scope` still intentionally raises: `effective_org_scope` resolution needs the
`organization` module's region/assignment data, which doesn't exist yet. Wiring it now would
mean either faking scope (a tenant-isolation regression) or duplicating business logic outside
its owning module — both forbidden for this phase. Likewise `require_permission` raises: the
RBAC permission matrix (Phase 2 §12.2) is authorization business data that isn't approved yet.
"""

from __future__ import annotations

from typing import AsyncIterator, Callable

from fastapi import Depends, Request

from raad.core.config.settings import Settings, get_settings
from raad.core.db.unit_of_work import UnitOfWork
from raad.core.di.container import Container
from raad.core.errors.exceptions import AuthenticationError
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.core.tenancy.scope import TenantRegionScope


def get_app_settings() -> Settings:
    return get_settings()


def get_correlation_id(request: Request) -> str | None:
    return request.headers.get("x-correlation-id")


def get_principal(request: Request) -> Principal:
    """Enforces that `SecurityContextMiddleware` resolved a `Principal` from the request's
    bearer JWT (§9.2, §18.2). Raises `AuthenticationError` (-> 401) if the header was absent,
    invalid, or expired."""
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None:
        raise AuthenticationError("Authentication is required.")
    return principal


# Alias matching the LLD's "current-user dependency" naming (§16.2) — same resolution chain,
# read at whichever call site the wording is clearer.
get_current_user = get_principal


def get_scope(principal: Principal = Depends(get_principal)) -> TenantRegionScope:
    """Resolves `effective_org_scope(principal)` (Phase 2 §17.4). Pending a concrete
    `ScopeResolver` implementation, which needs the `organization` module's region/assignment
    data."""
    raise NotImplementedError(
        "Tenant/region scope resolution is pending the organization module."
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


async def get_uow(
    container: Container = Depends(get_container),
) -> AsyncIterator[UnitOfWork]:
    """Request-scoped `UnitOfWork` (§9.1/§9.2): resolves a fresh instance per request via the
    DI container's factory binding, opens it (`async with`, which opens the session), and lets
    the caller's command handler commit/let-it-rollback before the session is closed here.
    Raises `LookupError` if `core/di` left `UnitOfWork` unbound (no `db.url` configured) —
    the same "fail loudly, don't fake it" policy as `get_scope`."""
    uow = container.resolve(UnitOfWork)
    async with uow:
        yield uow


def require_permission(permission: Permission) -> Callable[[Principal], Principal]:
    """Dependency factory: `Depends(require_permission(Permission("students.read")))`.
    Pending a concrete `PermissionEvaluator` bound in `core/di` — the RBAC permission matrix
    (Phase 2 §12.2) is authorization business data that isn't approved yet, so this raises
    rather than granting/denying on a guessed matrix (§16.2: authZ is a router-level
    dependency, never bypassable, but it also must never be a fake pass-through)."""

    def _dependency(principal: Principal = Depends(get_principal)) -> Principal:
        raise NotImplementedError(
            f"Permission evaluation for {permission!r} is pending the RBAC permission matrix "
            "and a bound PermissionEvaluator."
        )

    return _dependency
