"""Application-layer command validators for `transport_ops` (Backend LLD §4.1's application
table: "Contextual pre-conditions of a use-case"). These check pre-conditions that need
repository I/O — exactly why they're an application concern and not a domain one, mirroring
`fleet_device.application.validators`'s identical reasoning and exact `ensure_*` naming.

**Phases 10.1-10.6: none were defined.** `Student`/`Parent` declare no uniqueness constraint
beyond their own primary key (`domain/repositories.py`'s own docstrings), no cross-aggregate
reference existed yet (no `route_id`/`parent_id`/`trip_id` on `Student`, no `Student` reference
on `Parent`), and existence-checking the very aggregate a use-case operates *on* lives on each
service itself (`StudentApplicationService._get_student_or_raise`, mirroring `Organization
ApplicationService._get_organization_or_raise` — not a function here). Tenant scoping needs no
manual check either way, being resolved once at the edge (`.claude/rules/backend.md` #4).

**Phase 10.7 addition — `StudentParent` is the first aggregate in this module needing this
file.** It references two *other* aggregates (`Student`, `Parent`) rather than checking its own
existence, exactly the shape `fleet_device.application.validators.ensure_vehicle_exists` already
establishes for a `vehicle_id` referenced by a `DeviceAssignment` command:

- `ensure_student_exists` / `ensure_parent_exists` → the in-context FKs `student_parents.
  student_id → students.id` / `student_parents.parent_id → parents.id` (Database Design §6.4).
- `ensure_link_not_duplicate` → the composite primary key `(student_id, parent_id)` — defense
  in depth over the DB-enforced constraint, surfacing a typed `ConflictError` instead of a raw
  `IntegrityError`, the same pattern `fleet_device.ensure_terminal_id_available` establishes.
- `ensure_link_exists` → backs `unlink_parent_from_student`, load-or-404 for a not-found
  relationship, mirroring `ensure_vehicle_exists`'s own shape.

Cross-organization rejection is **not** here — it needs no repository I/O once `Student`/
`Parent` are already loaded, so it lives in the domain layer instead
(`domain/entities.py`'s `StudentParent.link` docstring explains the split).

**Phase 10.8: none added for `Driver` either**, for the identical reason Phases 10.1-10.6 gave —
no uniqueness constraint beyond its own primary key, no cross-aggregate reference, and its own
existence-checking lives on `DriverApplicationService._get_driver_or_raise`
(`application/services.py`), not a function here.
"""

from __future__ import annotations

from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.domain.entities import Parent, Student, StudentParent
from raad.modules.transport_ops.domain.value_objects import ParentId, StudentId


async def ensure_student_exists(
    uow: TransportOpsUnitOfWork, student_id: StudentId
) -> Student:
    student = await uow.students.get(student_id)
    if student is None:
        raise NotFoundError(f"Student {student_id} not found.")
    return student


async def ensure_parent_exists(
    uow: TransportOpsUnitOfWork, parent_id: ParentId
) -> Parent:
    parent = await uow.parents.get(parent_id)
    if parent is None:
        raise NotFoundError(f"Parent {parent_id} not found.")
    return parent


async def ensure_link_not_duplicate(
    uow: TransportOpsUnitOfWork, student_id: StudentId, parent_id: ParentId
) -> None:
    existing = await uow.student_parents.get(student_id, parent_id)
    if existing is not None:
        raise ConflictError(
            f"Parent {parent_id} is already linked to student {student_id}."
        )


async def ensure_link_exists(
    uow: TransportOpsUnitOfWork, student_id: StudentId, parent_id: ParentId
) -> StudentParent:
    link = await uow.student_parents.get(student_id, parent_id)
    if link is None:
        raise NotFoundError(
            f"No link between student {student_id} and parent {parent_id}."
        )
    return link
