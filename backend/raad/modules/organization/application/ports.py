"""Outbound ports the `organization` application layer depends on (Backend LLD §4.2).
`UnitOfWork` is the existing core abstraction (`core.db.unit_of_work`), extended here with
`organization`'s own repositories — exactly the pattern that module's own docstring anticipates,
and exactly what `iam.application.ports.IamUnitOfWork` already does. `Clock`/`IdGenerator` are
likewise existing core ports, used as constructor dependencies by the application services
(`services.py`) — never redefined here.

`core.db.unit_of_work` co-locates the abstract `UnitOfWork` with its concrete
`SqlAlchemyUnitOfWork` implementation in the same file, so importing the interface transitively
requires SQLAlchemy to be installed. Accepted deliberately here for the same reason
`iam.application.ports` accepts it: SQLAlchemy is an already-approved project dependency
(Phase 4.4), this application layer's own code never references it directly, and the LLD's own
`application/ports.py` contract skeleton (§4.2) explicitly expects `interface UnitOfWork` to be
referenced from exactly this file.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.db.unit_of_work import UnitOfWork
from raad.core.tenancy.principal import Principal, Role
from raad.modules.organization.domain.repositories import (
    OrganizationRepository,
    RegionRepository,
    ScopeAssignmentRepository,
)


class OrganizationUnitOfWork(UnitOfWork):
    """Bundles the repositories `organization`'s use-cases need onto one transaction
    boundary (LLD §8.2 contract skeleton style — plain attributes, matching
    `IamUnitOfWork`'s own style). The concrete implementation is
    `infra.repositories.SqlAlchemyOrganizationUnitOfWork`.

    `scope_assignments` added for `ScopeResolver` (Database Design §4.6) — see
    `domain/repositories.py`'s `ScopeAssignmentRepository` docstring."""

    organizations: OrganizationRepository
    regions: RegionRepository
    scope_assignments: ScopeAssignmentRepository


class IamProvisioningPort(ABC):
    """ADR-0017: creates the login-capable `iam.User` (role=org_admin) an Organization
    Onboarding workflow hands off to RAAD, via `iam`'s own public application-service
    surface — never its repository/ORM layer. A second, independent instance of the exact
    cross-context pattern `transport_ops.application.ports.UserProvisioningPort` already
    establishes (ADR-0003) — see that ADR's own "Extension" section. Owned by this module
    (the consumer), satisfied by `infra.adapters.IamUserProvisioningAdapter`.

    Returns a `(user_id, temporary_password)` pair — the plaintext temporary password is
    surfaced to the caller (the Founder/RAAD staff onboarding this organization) exactly once,
    for hand-off; it is never persisted or retrievable again afterward."""

    @abstractmethod
    async def create_user_with_temporary_password(
        self,
        *,
        organization_id: str,
        role: Role,
        email: str | None,
        phone: str | None,
        full_name: str,
        actor: Principal,
    ) -> tuple[str, str]:
        raise NotImplementedError

    @abstractmethod
    async def disable_user(self, *, user_id: str, actor: Principal) -> None:
        """Compensation for a partially-completed onboarding.

        Onboarding spans three modules and therefore three Units of Work — one database
        transaction cannot cover them (`.claude/rules/backend.md` #3 keeps each module's
        persistence its own). When a later step fails, the admin account already created for an
        organization that will not exist has to be revoked, or onboarding leaves a live login
        attached to a deactivated tenant. This is the saga's compensating action, not an
        ordinary lifecycle operation.
        """
        raise NotImplementedError


class BillingProvisioningPort(ABC):
    """ADR-0040 §5 — opens an Organization's subscription during onboarding.

    Same provisioning-port shape ADR-0003 established and ADR-0017 reused for
    `IamProvisioningPort`: `organization` depends on the *abstraction* only, and the concrete
    adapter lives in `core/di/` (the composition root), so this module never imports `billing`.

    **No date arithmetic here.** The adapter delegates to `BillingApplicationService.
    open_organization_subscription`, which already computes period start/end from the plan's own
    billing cycle and issues the first invoice. Re-deriving those dates on this side would be a
    second, drifting implementation of RAAD's billing calendar.
    """

    @abstractmethod
    async def ensure_plan_is_offerable(self, *, plan_id: str) -> None:
        """Validates the plan **before** onboarding commits anything at all.

        The single most valuable ordering decision in this workflow. Onboarding cannot be one
        transaction, so the next best guarantee is that its most likely failure — a plan id that
        does not exist or is no longer sold — is discovered while there is still nothing to undo.
        Raises `NotFoundError` for an unknown plan and `DomainError` for an inactive one; both
        reach the caller as a 4xx before an `Organization` row is written.
        """
        raise NotImplementedError

    @abstractmethod
    async def open_subscription_for_organization(
        self, *, organization_id: str, plan_id: str, actor: Principal
    ) -> None:
        raise NotImplementedError
