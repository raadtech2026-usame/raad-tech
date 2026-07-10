"""Shared FastAPI dependencies (Backend LLD §9.2, §16.2): auth, tenant/region scope, UoW,
pagination.

Only the dependency *shape* (the resolution chain: request -> principal -> scope -> ...) is
established in this phase. `get_principal` and `get_scope` intentionally raise rather than
fake an authenticated caller — JWT verification lives in `core/security` and scope
resolution needs the `organization`/`iam` modules' data, neither of which exists yet. Wiring
them now would mean either faking authentication (a security regression) or duplicating
business logic outside its owning module — both forbidden for this phase.
"""
from __future__ import annotations

from fastapi import Depends, Request

from raad.core.config.settings import Settings, get_settings
from raad.core.errors.exceptions import AuthenticationError
from raad.core.tenancy.principal import Principal
from raad.core.tenancy.scope import TenantRegionScope


def get_app_settings() -> Settings:
    return get_settings()


def get_correlation_id(request: Request) -> str | None:
    return request.headers.get("x-correlation-id")


def get_principal(request: Request) -> Principal:
    """Resolves the authenticated Principal from the request's bearer JWT (§9.2, §18.2).
    Pending `core/security` (JWT verification) and the `iam` module (token issuance)."""
    raise AuthenticationError("Authentication is not yet wired (core/security is pending).")


def get_scope(principal: Principal = Depends(get_principal)) -> TenantRegionScope:
    """Resolves `effective_org_scope(principal)` (Phase 2 §17.4). Pending a concrete
    `ScopeResolver` implementation, which needs the `organization` module's region/assignment
    data."""
    raise NotImplementedError(
        "Tenant/region scope resolution is pending the organization module."
    )
