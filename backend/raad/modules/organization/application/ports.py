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

from raad.core.db.unit_of_work import UnitOfWork
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
