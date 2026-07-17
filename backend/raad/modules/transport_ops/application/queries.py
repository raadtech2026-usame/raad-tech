"""Transport Operations application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite
read-models). DTOs are plain dataclasses — the boundary between the domain's aggregates and any
future API/infra layer, so neither ever depends on the other's internal shape. Mirrors
`organization.application.queries`'s shape exactly: id fields become `str(vo)`, enum/status
fields become `.value`, timestamps (none on `Student` — see `domain/entities.py`) would stay
native `datetime`, never `.isoformat()`-stringified at this layer.

**`ListStudentsQuery` establishes a new pattern in this codebase — flagged, not silently
copied.** No `List*Query` exists in any of `iam`/`organization`/`fleet_device`/`tracking`'s
application layers (their only "many" reads are relationship-scoped, e.g. `GetVehiclePositionHistoryQuery(trip_id)`,
never an unscoped "list everything in my tenant"), and `core/pagination` is an empty module — no
limit/offset/cursor convention exists to reuse. `ListStudentsQuery` therefore carries no fields
at all (implicitly tenant-scoped, matching `StudentRepository.list_all`'s own no-parameter
shape); pagination is deferred to whichever later phase actually needs it, rather than inventing
an unapproved shape now.

**`StudentSummaryDTO` also establishes a new pattern — flagged.** No module in this codebase has
a "summary" vs. "full" DTO distinction; every aggregate has exactly one DTO shape. Built here
only because the task explicitly requests it: a lighter projection for `list_students` (omitting
`organization_id`/`external_ref`, which a listing view doesn't need) alongside the full
`StudentDTO` for `get_student_by_id`.
"""

from __future__ import annotations

from dataclasses import dataclass

from raad.modules.transport_ops.domain.entities import Parent, Student, StudentParent


@dataclass(frozen=True)
class GetStudentByIdQuery:
    student_id: str


@dataclass(frozen=True)
class ListStudentsQuery:
    pass


@dataclass(frozen=True)
class StudentDTO:
    id: str
    organization_id: str
    full_name: str
    external_ref: str | None
    status: str


@dataclass(frozen=True)
class StudentSummaryDTO:
    id: str
    full_name: str
    status: str


def student_to_dto(student: Student) -> StudentDTO:
    """Shared mapper — the only place a `Student` aggregate is projected into its full DTO."""
    return StudentDTO(
        id=str(student.id),
        organization_id=str(student.organization_id),
        full_name=student.full_name,
        external_ref=student.external_ref,
        status=student.status.value,
    )


def student_to_summary_dto(student: Student) -> StudentSummaryDTO:
    """Shared mapper — the only place a `Student` aggregate is projected into its summary DTO
    (`ListStudentsQuery`'s read shape)."""
    return StudentSummaryDTO(
        id=str(student.id),
        full_name=student.full_name,
        status=student.status.value,
    )


@dataclass(frozen=True)
class GetParentByIdQuery:
    parent_id: str


@dataclass(frozen=True)
class ListParentsQuery:
    pass


@dataclass(frozen=True)
class ParentDTO:
    id: str
    organization_id: str
    user_id: str
    full_name: str
    phone: str | None
    status: str


@dataclass(frozen=True)
class ParentSummaryDTO:
    id: str
    full_name: str
    status: str


def parent_to_dto(parent: Parent) -> ParentDTO:
    """Shared mapper — the only place a `Parent` aggregate is projected into its full DTO,
    mirroring `student_to_dto`'s exact shape."""
    return ParentDTO(
        id=str(parent.id),
        organization_id=str(parent.organization_id),
        user_id=str(parent.user_id),
        full_name=parent.full_name,
        phone=str(parent.phone) if parent.phone is not None else None,
        status=parent.status.value,
    )


def parent_to_summary_dto(parent: Parent) -> ParentSummaryDTO:
    """Shared mapper — the only place a `Parent` aggregate is projected into its summary DTO
    (`ListParentsQuery`'s read shape), mirroring `student_to_summary_dto`'s exact shape.
    """
    return ParentSummaryDTO(
        id=str(parent.id), full_name=parent.full_name, status=parent.status.value
    )


@dataclass(frozen=True)
class ListParentsForStudentQuery:
    student_id: str


@dataclass(frozen=True)
class ListStudentsForParentQuery:
    parent_id: str


@dataclass(frozen=True)
class StudentParentDTO:
    """The raw link record — returned by `link_parent_to_student` (Phase 10.7). The two "list X
    for Y" read paths return the richer `ParentForStudentDTO`/`StudentForParentDTO` below
    instead (joining in the referenced aggregate's own fields), since a bare link record with
    only ids is of little use to an API caller asking "which parents does this student have" —
    flagged as a deliberate shape choice, not a silently invented one."""

    student_id: str
    parent_id: str
    relationship: str | None
    is_primary: bool


@dataclass(frozen=True)
class ParentForStudentDTO:
    """`Parent`'s own fields plus this link's `relationship`/`is_primary` — the read shape for
    `ListParentsForStudentQuery` (Phase 10.7)."""

    parent_id: str
    full_name: str
    phone: str | None
    status: str
    relationship: str | None
    is_primary: bool


@dataclass(frozen=True)
class StudentForParentDTO:
    """`Student`'s own fields plus this link's `relationship`/`is_primary` — the read shape for
    `ListStudentsForParentQuery` (Phase 10.7)."""

    student_id: str
    full_name: str
    status: str
    relationship: str | None
    is_primary: bool


def student_parent_to_dto(link: StudentParent) -> StudentParentDTO:
    """Shared mapper — the only place a `StudentParent` aggregate is projected into its raw
    link DTO."""
    return StudentParentDTO(
        student_id=str(link.student_id),
        parent_id=str(link.parent_id),
        relationship=link.relationship,
        is_primary=link.is_primary,
    )


def parent_for_student_to_dto(
    parent: Parent, link: StudentParent
) -> ParentForStudentDTO:
    return ParentForStudentDTO(
        parent_id=str(parent.id),
        full_name=parent.full_name,
        phone=str(parent.phone) if parent.phone is not None else None,
        status=parent.status.value,
        relationship=link.relationship,
        is_primary=link.is_primary,
    )


def student_for_parent_to_dto(
    student: Student, link: StudentParent
) -> StudentForParentDTO:
    return StudentForParentDTO(
        student_id=str(student.id),
        full_name=student.full_name,
        status=student.status.value,
        relationship=link.relationship,
        is_primary=link.is_primary,
    )
