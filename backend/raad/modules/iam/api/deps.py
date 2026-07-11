"""FastAPI dependency wiring for `iam` (Backend LLD §9.2/§16.2). Resolves the DI-container-
bound `IamUnitOfWork` and application services — the only place this module's HTTP layer
touches `core.di`; routers never import the container directly beyond this file, and never
construct a repository or touch SQLAlchemy.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.services import (
    AuthApplicationService,
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
    entering keeps each service call a fully self-contained transaction, as designed."""
    return container.resolve(IamUnitOfWork)


def get_user_service(
    container: Container = Depends(get_container),
) -> UserApplicationService:
    return container.resolve(UserApplicationService)


def get_auth_service(
    container: Container = Depends(get_container),
) -> AuthApplicationService:
    return container.resolve(AuthApplicationService)
