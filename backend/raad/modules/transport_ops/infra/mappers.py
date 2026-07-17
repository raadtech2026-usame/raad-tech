"""ORM ↔ Domain mappers for `transport_ops` (Backend LLD §7.1 "aggregate-in/aggregate-out";
§17 `db`). Mappers own **every** conversion between SQLAlchemy rows and domain objects —
repositories (`repositories.py`) never construct or read ORM columns directly outside calling
these functions, and never return an ORM model to a caller. Mirrors
`organization.infra.mappers`'s `existing=` in-place-update pattern exactly.
"""

from __future__ import annotations

from raad.modules.transport_ops.domain.entities import Parent, Student
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
    StudentId,
    StudentStatus,
    UserId,
)
from raad.modules.transport_ops.infra.models import ParentModel, StudentModel


def student_to_model(
    student: Student, *, existing: StudentModel | None = None
) -> StudentModel:
    """Projects a `Student` aggregate onto its ORM row. If `existing` is given, mutates and
    returns that same instance (so the SQLAlchemy session keeps tracking the one row it already
    knows about, rather than a duplicate) — otherwise constructs a new `StudentModel`.
    """
    model = existing if existing is not None else StudentModel(id=str(student.id))
    model.organization_id = str(student.organization_id)
    model.full_name = student.full_name
    model.external_ref = student.external_ref
    model.status = student.status.value
    return model


def model_to_student(model: StudentModel) -> Student:
    return Student(
        id=StudentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        full_name=model.full_name,
        external_ref=model.external_ref,
        status=StudentStatus(model.status),
    )


def parent_to_model(
    parent: Parent, *, existing: ParentModel | None = None
) -> ParentModel:
    """Projects a `Parent` aggregate onto its ORM row, mirroring `student_to_model`'s exact
    `existing=` in-place-update pattern."""
    model = existing if existing is not None else ParentModel(id=str(parent.id))
    model.organization_id = str(parent.organization_id)
    model.user_id = str(parent.user_id)
    model.full_name = parent.full_name
    model.phone = str(parent.phone) if parent.phone is not None else None
    model.status = parent.status.value
    return model


def model_to_parent(model: ParentModel) -> Parent:
    return Parent(
        id=ParentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        user_id=UserId(model.user_id),
        full_name=model.full_name,
        phone=PhoneNumber(model.phone) if model.phone else None,
        status=ParentStatus(model.status),
    )
