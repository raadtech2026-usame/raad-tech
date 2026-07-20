"""Shared FastAPI dependencies (Backend LLD §9.2, §16.2): auth, tenant/region scope, UoW,
pagination.

`get_principal` reads the `Principal` that `SecurityContextMiddleware`
(`interfaces/http/middleware.py`) already verified and attached to `request.state.principal`
— it only *enforces* that one was found, keeping JWT verification itself out of the dependency
layer.

**Architecture Resolution (ADR-0004, ADR-0005, Backend Stabilization phase):** `require_permission`
and `get_scope` now resolve for real, via the DI-bound `PermissionEvaluator`
(`iam.infra.adapters.IamPermissionEvaluator`, backed by the `role_permissions` table — Database
Design §4.4) and `ScopeResolver` (`organization.infra.adapters.OrganizationScopeResolver`,
backed by `region_assignments`/`support_assignments` — Database Design §4.6). Both still raise
`LookupError` if `core/di` left them unbound (no `db.url` configured) — the same "fail loudly,
don't fake it" policy this codebase applies to every other pending-infra port.
"""

from __future__ import annotations

from typing import Awaitable, AsyncIterator, Callable

from fastapi import Depends, Request

from raad.core.config.settings import Settings, get_settings
from raad.core.db.unit_of_work import UnitOfWork
from raad.core.di.container import Container
from raad.core.errors.exceptions import AuthenticationError, AuthorizationError
from raad.core.security.permissions import Permission, PermissionEvaluator
from raad.core.tenancy.principal import Principal
from raad.core.tenancy.resolver import ScopeResolver
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


async def get_scope(
    request: Request, principal: Principal = Depends(get_principal)
) -> TenantRegionScope:
    """Resolves `effective_org_scope(principal)` (Phase 2 §17.4) via the DI-bound
    `ScopeResolver`. Raises `LookupError` (-> 500) if unbound (no `db.url` configured)."""
    container = get_container(request)
    resolver = container.resolve(ScopeResolver)
    return await resolver.effective_org_scope(principal)


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


def require_permission(
    permission: Permission,
) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: `Depends(require_permission(Permission("students.read")))`.
    Resolves the DI-bound `PermissionEvaluator` (Database Design §4.4's `role_permissions`
    matrix) and raises `AuthorizationError` (-> 403) if the principal's role lacks the given
    permission — §16.2: authZ is a router-level dependency, never bypassable, and (as of the
    Backend Stabilization phase) no longer a guaranteed-fail placeholder either."""

    async def _dependency(
        request: Request, principal: Principal = Depends(get_principal)
    ) -> Principal:
        container = get_container(request)
        evaluator = container.resolve(PermissionEvaluator)
        if not await evaluator.has_permission(principal, permission):
            raise AuthorizationError(f"Missing permission: {permission}")
        return principal

    return _dependency
