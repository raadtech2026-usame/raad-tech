"""Transport Operations domain layer (Backend LLD §5; Database Design §6) — Phase 10.1 scope.

Framework-free: entities/value objects/events/repository interfaces only. No application
services, no infra, no DI — those are later phases. Public surface of this package.

Scope: `Student` only (Database Design §6.2). `Parent`/`student_parents` (§6.3/§6.4),
`Route`/`Stop` (§6.5/§6.6), `student_assignments` (§6.7 — the CR-1 access gate), and
`Trip`/`trip_students` (§6.8/§6.9) are deliberately deferred to later phases — confirmed with
the user before implementing, see `entities.py`'s module docstring for the full scope note.
`services.py`/`policies.py` define nothing yet (see their own module docstrings for why) and are
not re-exported here — only `tracking.domain.__init__` (whose `services.py`/`policies.py` do
define something) re-exports from those files, matching the established convention.
"""

from raad.modules.transport_ops.domain.entities import Student
from raad.modules.transport_ops.domain.repositories import StudentRepository
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    StudentId,
    StudentStatus,
)

__all__ = [
    "OrganizationId",
    "Student",
    "StudentId",
    "StudentRepository",
    "StudentStatus",
]
