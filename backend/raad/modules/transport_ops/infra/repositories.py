"""SQLAlchemy repository implementations for `transport_ops` (Backend LLD §7, §8; Database
Design §6.2). Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` — the repository never
returns an ORM model, only the `Student` aggregate `modules/transport_ops/domain/repositories.py`
declares (§7.1's "aggregate-in/aggregate-out" rule).

**The identity-map problem this file solves** — identical to `iam.infra.repositories`'s and
`organization.infra.repositories`'s own docstrings: because `get()` returns a plain domain
object (not the tracked ORM row), a handler that does
`student = await uow.students.get(id); student.activate(...)` mutates only that detached domain
object — SQLAlchemy's session never sees the change, since it only dirty-tracks its own
`StudentModel` instances. The application layer never re-calls `add()` after such a mutation
(reserved for genuinely new aggregates, `application/services.py`), so this layer bridges the
gap: the repository keeps a `{id: (domain_object, orm_row)}` map of everything it has returned
or added, and `flush_tracked_changes()` re-projects every tracked domain object onto its row via
the mapper immediately before commit — called by `SqlAlchemyTransportOpsUnitOfWork.commit()`,
below.

**`list_all` is not yet tenant-scoped — flagged, not silently shipped as solved.** Phase 10.2's
`StudentRepository.list_all` interface deliberately takes no `organization_id` parameter,
since `.claude/rules/backend.md` #4 says tenant context should be "resolved once at the edge
... and injected into every repository query automatically." That edge resolution
(`core.tenancy.ScopeResolver` producing a `TenantRegionScope` per request) is not bound
anywhere in `core/di/bootstrap.py` yet for *any* module (its own docstring lists
`ScopeResolver` among the ports "bound here once their owning module/infra is implemented in a
later phase") — `iam.infra.repositories.SqlAlchemyUserRepository` notes the identical gap
("[tenant/region scoping] applies once a scoped listing use-case exists, via `list_scoped`"),
but `list_all` here *is* that first scoped-listing use-case, so the gap can no longer be
deferred by simply not implementing the method. Implemented via `list_scoped` (reusing the
existing soft-delete-aware filter mechanics rather than hand-rolling a duplicate query) with an
explicit unrestricted `TenantRegionScope` — functionally identical to no filtering, but written
so that swapping in a real per-request scope is a one-line change once `ScopeResolver` is wired
system-wide, rather than a rewrite. Wiring that resolver is out of this phase's scope (it is a
cross-cutting, all-modules concern, not a Student-specific one) and is not attempted here.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.domain.entities import Student
from raad.modules.transport_ops.domain.repositories import StudentRepository
from raad.modules.transport_ops.domain.value_objects import StudentId
from raad.modules.transport_ops.infra.mappers import model_to_student, student_to_model
from raad.modules.transport_ops.infra.models import StudentModel


class SqlAlchemyStudentRepository(
    SqlAlchemyRepositoryBase[StudentModel], StudentRepository
):
    model = StudentModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Student, StudentModel]] = {}

    async def get(self, student_id: StudentId) -> Student | None:
        row = await self.get_by_id(str(student_id))
        return self._track(row)

    def add(self, student: Student) -> None:
        model = student_to_model(student)
        super().add(model)
        self._tracked[str(student.id)] = (student, model)

    async def list_all(self) -> list[Student]:
        """See module docstring: unrestricted `TenantRegionScope` today, pending a system-wide
        `ScopeResolver` binding — not a Student-specific gap."""
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_student(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for student, model in self._tracked.values():
            student_to_model(student, existing=model)

    def _track(self, row: StudentModel | None) -> Student | None:
        if row is None:
            return None
        student = model_to_student(row)
        self._tracked[row.id] = (student, row)
        return student


class SqlAlchemyTransportOpsUnitOfWork(SqlAlchemyUnitOfWork, TransportOpsUnitOfWork):
    """Concrete `TransportOpsUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `transport_ops`'s
    one repository once the session is open, and re-syncs every tracked aggregate's in-place
    mutations onto its ORM row (`flush_tracked_changes`, above) immediately before delegating
    to `SqlAlchemyUnitOfWork.commit()` — which still owns the actual outbox-write +
    session-commit behavior, preserved exactly (§8.3), via `super().commit()`. Identical shape
    to `organization.infra.repositories.SqlAlchemyOrganizationUnitOfWork`.
    """

    students: SqlAlchemyStudentRepository

    async def __aenter__(self) -> "SqlAlchemyTransportOpsUnitOfWork":
        await super().__aenter__()
        self.students = SqlAlchemyStudentRepository(self.session)
        return self

    async def commit(self) -> None:
        self.students.flush_tracked_changes()
        await super().commit()
