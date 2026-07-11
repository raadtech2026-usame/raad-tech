"""Outbound ports the `iam` application layer depends on (Backend LLD §4.2). `UnitOfWork` is
the existing core abstraction (`core.db.unit_of_work`), extended here with `iam`'s own
repositories — exactly the pattern that module's own docstring anticipates ("per-module
repository properties ... are added by each module's own UoW extension once that module's
domain/infra exist"). `Clock`, `IdGenerator`, `TokenService`, `PasswordHasher`, and
`PasswordPolicy` are likewise existing core ports, used as constructor dependencies by the
application services (`services.py`) — never redefined here.

`core.db.unit_of_work` co-locates the abstract `UnitOfWork` with its concrete
`SqlAlchemyUnitOfWork` implementation in the same file, so importing the interface
transitively requires SQLAlchemy to be installed. That's accepted deliberately here — unlike
the domain layer's zero-tolerance rule (Phase 5.1's `core.db.repository` situation),
SQLAlchemy is an already-approved project dependency (Phase 4.4), this application layer's own
code never references it directly, and the LLD's own `application/ports.py` contract skeleton
(§4.2) explicitly expects `interface UnitOfWork` to be referenced from exactly this file.
"""

from __future__ import annotations

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.iam.domain.repositories import RefreshTokenRepository, UserRepository


class IamUnitOfWork(UnitOfWork):
    """Bundles the two repositories `iam`'s use-cases need onto one transaction boundary (LLD
    §8.2 contract skeleton: `trips: TripRepository`, etc. — declared as plain attributes,
    matching that skeleton's own style, not abstract methods). The concrete implementation
    (a future `SqlAlchemyIamUnitOfWork(SqlAlchemyUnitOfWork, IamUnitOfWork)`) is infra, not
    implemented in this phase."""

    users: UserRepository
    refresh_tokens: RefreshTokenRepository
