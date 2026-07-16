"""Outbound ports the `transport_ops` application layer depends on (Backend LLD §4.2).
`UnitOfWork` is the existing core abstraction (`core.db.unit_of_work`), extended here with
`transport_ops`'s own repositories — exactly the pattern that module's own docstring
anticipates, and exactly what `organization.application.ports.OrganizationUnitOfWork` already
does. `Clock`/`IdGenerator` are likewise existing core ports, used as constructor dependencies
by the application service (`services.py`) — never redefined here.

`core.db.unit_of_work` co-locates the abstract `UnitOfWork` with its concrete
`SqlAlchemyUnitOfWork` implementation in the same file, so importing the interface transitively
requires SQLAlchemy to be installed. Accepted deliberately here for the same reason
`organization.application.ports` accepts it: SQLAlchemy is an already-approved project
dependency (Phase 4.4), this application layer's own code never references it directly, and the
LLD's own `application/ports.py` contract skeleton (§4.2) explicitly expects `interface
UnitOfWork` to be referenced from exactly this file. This is *not* the forbidden "implement
SQLAlchemy" this phase's own scope excludes — no SQLAlchemy type, session, or query appears
anywhere in this module's `application/` code.

No bespoke read-only port (the `tracking.application.ports.LatestPositionPort` shape) is needed
this phase — every Student read (`GetStudentByIdQuery`/`ListStudentsQuery`) is fully served by
`StudentRepository` through the `TransportOpsUnitOfWork` below; there is no non-repository-backed
data source like `tracking`'s Redis latest-position cache for `Student`.
"""

from __future__ import annotations

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.transport_ops.domain.repositories import StudentRepository


class TransportOpsUnitOfWork(UnitOfWork):
    """Bundles the one repository this phase's use-cases need onto one transaction boundary
    (LLD §8.2 contract skeleton style — plain attributes, matching `OrganizationUnitOfWork`'s
    own style). The concrete implementation (a future `SqlAlchemyTransportOpsUnitOfWork
    (SqlAlchemyUnitOfWork, TransportOpsUnitOfWork)`) is infra, not implemented in this phase.
    """

    students: StudentRepository
