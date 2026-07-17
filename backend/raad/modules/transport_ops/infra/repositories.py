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

**Phase 10.7 addition: `SqlAlchemyStudentParentRepository`.** Cannot reuse `SqlAlchemyRepository
Base.get_by_id`/its identity-map keying — both assume a single `.id` column, and
`student_parents` has a composite primary key instead (`domain/repositories.py`'s Phase 10.7
docstring). `get`/`list_by_student`/`list_by_parent` therefore issue their own `select()`
statements directly rather than delegating to the base class's `get_by_id`, and the identity
map is keyed by the `(student_id, parent_id)` tuple. `remove()` is new too — `StudentParent`'s
only two lifecycle actions are a real INSERT (`add`) and a real DELETE (`remove`); there is no
in-place field-level UPDATE the way `Student`/`Parent` get via `flush_tracked_changes`, so this
repository defines no such method and `SqlAlchemyTransportOpsUnitOfWork.commit()` below calls
none for it.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.domain.entities import Parent, Student, StudentParent
from raad.modules.transport_ops.domain.repositories import (
    ParentRepository,
    StudentParentRepository,
    StudentRepository,
)
from raad.modules.transport_ops.domain.value_objects import ParentId, StudentId
from raad.modules.transport_ops.infra.mappers import (
    model_to_parent,
    model_to_student,
    model_to_student_parent,
    parent_to_model,
    student_parent_to_model,
    student_to_model,
)
from raad.modules.transport_ops.infra.models import (
    ParentModel,
    StudentModel,
    StudentParentModel,
)


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


class SqlAlchemyParentRepository(
    SqlAlchemyRepositoryBase[ParentModel], ParentRepository
):
    """Mirrors `SqlAlchemyStudentRepository`'s exact identity-map/`flush_tracked_changes`
    shape, including `list_all`'s same unrestricted-`TenantRegionScope` caveat (Phase 10.3's
    module docstring, unchanged this phase — still a system-wide `ScopeResolver` gap, not a
    `Parent`-specific one)."""

    model = ParentModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Parent, ParentModel]] = {}

    async def get(self, parent_id: ParentId) -> Parent | None:
        row = await self.get_by_id(str(parent_id))
        return self._track(row)

    def add(self, parent: Parent) -> None:
        model = parent_to_model(parent)
        super().add(model)
        self._tracked[str(parent.id)] = (parent, model)

    async def list_all(self) -> list[Parent]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_parent(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for parent, model in self._tracked.values():
            parent_to_model(parent, existing=model)

    def _track(self, row: ParentModel | None) -> Parent | None:
        if row is None:
            return None
        parent = model_to_parent(row)
        self._tracked[row.id] = (parent, row)
        return parent


class SqlAlchemyStudentParentRepository(StudentParentRepository):
    """See module docstring's Phase 10.7 addition for why this does **not** compose
    `SqlAlchemyRepositoryBase[StudentParentModel]` the way `SqlAlchemyStudentRepository`/
    `SqlAlchemyParentRepository` do — the composite-key shape doesn't fit that base class's
    single-`.id` assumptions, so this repository is a small, self-contained implementation
    instead."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tracked: dict[
            tuple[str, str], tuple[StudentParent, StudentParentModel]
        ] = {}

    async def get(
        self, student_id: StudentId, parent_id: ParentId
    ) -> StudentParent | None:
        statement = select(StudentParentModel).where(
            StudentParentModel.student_id == str(student_id),
            StudentParentModel.parent_id == str(parent_id),
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return self._track(row)

    def add(self, link: StudentParent) -> None:
        model = student_parent_to_model(link)
        self._session.add(model)
        self._tracked[(str(link.student_id), str(link.parent_id))] = (link, model)

    async def remove(self, link: StudentParent) -> None:
        key = (str(link.student_id), str(link.parent_id))
        tracked = self._tracked.pop(key, None)
        if tracked is None:
            # The application layer always calls get()/ensure_link_exists() before unlink()
            # (`application/services.py`), which populates `_tracked` - unreachable in
            # practice. Failing loudly here rather than silently no-op-ing, matching this
            # codebase's "fail loudly, don't fake it" posture (core/di/bootstrap.py's own
            # module docstring).
            raise LookupError(
                f"Cannot remove StudentParent({link.student_id}, {link.parent_id}): not "
                "tracked by this repository (call get() first)."
            )
        _, model = tracked
        # `AsyncSession.delete()` is itself a coroutine (unlike `.add()`) - it may need to
        # load relationships/cascade before marking the row for deletion. Found live: a
        # synchronous, un-awaited call here silently no-ops (the coroutine is created but
        # never scheduled), so the row survives commit - caught by
        # `test_transport_ops_student_parent_repository.py`'s round-trip test.
        await self._session.delete(model)

    async def list_by_student(self, student_id: StudentId) -> list[StudentParent]:
        statement = select(StudentParentModel).where(
            StudentParentModel.student_id == str(student_id)
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]

    async def list_by_parent(self, parent_id: ParentId) -> list[StudentParent]:
        statement = select(StudentParentModel).where(
            StudentParentModel.parent_id == str(parent_id)
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]

    def _track(self, row: StudentParentModel | None) -> StudentParent | None:
        if row is None:
            return None
        link = model_to_student_parent(row)
        self._tracked[(row.student_id, row.parent_id)] = (link, row)
        return link


class SqlAlchemyTransportOpsUnitOfWork(SqlAlchemyUnitOfWork, TransportOpsUnitOfWork):
    """Concrete `TransportOpsUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `transport_ops`'s
    repositories once the session is open, and re-syncs every tracked aggregate's in-place
    mutations onto its ORM row (`flush_tracked_changes`, above) immediately before delegating
    to `SqlAlchemyUnitOfWork.commit()` — which still owns the actual outbox-write +
    session-commit behavior, preserved exactly (§8.3), via `super().commit()`. Identical shape
    to `organization.infra.repositories.SqlAlchemyOrganizationUnitOfWork`, which already
    bundles two repositories (`organizations`/`regions`) the same way `students`/`parents` do
    here as of Phase 10.6; `student_parents` (Phase 10.7) joins the same way again — but needs
    no `flush_tracked_changes()` call of its own, per `SqlAlchemyStudentParentRepository`'s own
    docstring.
    """

    students: SqlAlchemyStudentRepository
    parents: SqlAlchemyParentRepository
    student_parents: SqlAlchemyStudentParentRepository

    async def __aenter__(self) -> "SqlAlchemyTransportOpsUnitOfWork":
        await super().__aenter__()
        self.students = SqlAlchemyStudentRepository(self.session)
        self.parents = SqlAlchemyParentRepository(self.session)
        self.student_parents = SqlAlchemyStudentParentRepository(self.session)
        return self

    async def commit(self) -> None:
        self.students.flush_tracked_changes()
        self.parents.flush_tracked_changes()
        await super().commit()
