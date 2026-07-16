"""Transport Operations application layer (Backend LLD §4) — Phase 10.2 scope.

Orchestration only: loads the `Student` aggregate via the repository bound to
`TransportOpsUnitOfWork`, invokes domain behavior, records the resulting `DomainEvent`s,
commits, and returns a DTO. No FastAPI/SQLAlchemy, no infra, no business rules (those live in
`modules/transport_ops/domain`). Public surface of this package.

Scope: `Student` lifecycle only, matching `domain/__init__.py`'s `Student`-only scope.
`StudentAssignment`/`Parent`/`Route`/`Trip` application use-cases are deliberately deferred to
later phases, alongside their domain layers.
"""

from raad.modules.transport_ops.application.commands import (
    ActivateStudentCommand,
    DisableStudentCommand,
    EnrollStudentCommand,
    GraduateStudentCommand,
    TransferStudentCommand,
    UpdateStudentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetStudentByIdQuery,
    ListStudentsQuery,
    StudentDTO,
    StudentSummaryDTO,
)
from raad.modules.transport_ops.application.services import StudentApplicationService

__all__ = [
    "ActivateStudentCommand",
    "DisableStudentCommand",
    "EnrollStudentCommand",
    "GetStudentByIdQuery",
    "GraduateStudentCommand",
    "ListStudentsQuery",
    "StudentApplicationService",
    "StudentDTO",
    "StudentSummaryDTO",
    "TransferStudentCommand",
    "TransportOpsUnitOfWork",
    "UpdateStudentCommand",
]
