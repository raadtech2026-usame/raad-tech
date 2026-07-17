"""HTTP surface of the `transport_ops` module (C4) — Phase 10.4. `students_router` mounts at
`/api/v1/students` (`interfaces/http/api_v1.py`); `parents_router`/`routes_router`/
`trips_router` remain empty — Phase 10.1-10.3 built only the `Student` aggregate, and this
phase's own scope is the Student API only.

Thin controllers only (Backend LLD §16.2): parse the request DTO, call exactly one
`StudentApplicationService` method, return the response DTO. No business logic, no repository/
SQLAlchemy access, no aggregate manipulation — every error raised by the application/domain
layers already maps to the standard `ErrorEnvelope` via the global exception handlers
(`core/errors/handlers.py`, registered once in `main.py`); routers never build an error
response themselves. Mirrors `organization`/`fleet_device`/`tracking.api.routers`'s shape
exactly, including the `require_permission`-pending-RBAC-matrix posture
(`interfaces/http/deps.py`): every route below is authorization-gated the same way, so it
currently raises `NotImplementedError` (500) rather than a guessed permission matrix, per API
Contracts §4.3's role column ("Org Admin") and §3.1's authorization layering.

**Five routes, matching API Contracts §4.3's `/students` rows exactly** (lines 122-123):
- `POST /students` — enroll (the doc's uniform "`GET/POST /students`" create half)
- `GET /students` — list (the doc's uniform "`GET/POST /students`" list half) — the **first
  list endpoint in this codebase**: `iam`/`organization`/`fleet_device`/`tracking` all
  deliberately deferred their own `GET /x` (list) routes because no listing use-case existed
  in their Application layers yet. `transport_ops` is different: Phase 10.2 already built
  `ListStudentsQuery`/`list_students`, and Phase 10.3 already gave it a working (if
  tenant-*un*scoped — see that phase's own flagged gap, `infra/repositories.py`'s module
  docstring) infra implementation. Declining to expose it here would mean sitting on a
  complete, working use-case for no documented reason — so, unlike the precedent modules, this
  route **is** implemented, carrying the inherited scoping caveat forward via this docstring
  rather than silently presenting it as production-ready.
- `GET /students/{id}` — get by id (uniform CRUD, API Contracts §4 preamble)
- `PATCH /students/{id}` — update `full_name`/`external_ref` (uniform CRUD; see
  `UpdateStudentRequest`'s docstring for why `status` is not accepted here)
- `POST /students/{id}/status` — activate/disable/graduate/transfer, dispatched by the
  `status` value (API Contracts §4.3 line 123 verbatim; see `UpdateStudentStatusRequest`'s
  docstring for the `active`-is-also-accepted interpretation)

**Endpoints deliberately not implemented** (documented, not silently dropped):
- `DELETE /students/{id}` (uniform-CRUD soft delete, §4 preamble) — `Student` has no
  soft-delete domain behavior (Database Design §9 keeps soft delete and business status
  explicitly separate concepts, `deleted_at` vs. `status`); same deferral `iam`/`fleet_device`
  already apply to `DELETE /users`/`DELETE /vehicles`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raad.core.errors.exceptions import ValidationError
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import require_permission
from raad.modules.transport_ops.api.deps import (
    get_student_service,
    get_transport_ops_uow,
)
from raad.modules.transport_ops.api.schemas import (
    EnrollStudentRequest,
    StudentResponse,
    StudentSummaryResponse,
    UpdateStudentRequest,
    UpdateStudentStatusRequest,
)
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

students_router = APIRouter()
parents_router = APIRouter()
routes_router = APIRouter()
trips_router = APIRouter()


def _student_dto_to_response(student: StudentDTO) -> StudentResponse:
    return StudentResponse(
        id=student.id,
        organization_id=student.organization_id,
        full_name=student.full_name,
        external_ref=student.external_ref,
        status=student.status,
    )


def _student_summary_dto_to_response(
    student: StudentSummaryDTO,
) -> StudentSummaryResponse:
    return StudentSummaryResponse(
        id=student.id, full_name=student.full_name, status=student.status
    )


@students_router.post(
    "",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a new student",
    description=(
        "Org Admin (API Contracts §4.3). Authorization uses `require_permission` — pending "
        "the approved RBAC permission matrix, so this currently raises `NotImplementedError` "
        "(500) rather than a guessed matrix, matching `organization`/`fleet_device`'s posture."
    ),
)
async def enroll_student(
    body: EnrollStudentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.create"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentResponse:
    command = EnrollStudentCommand(
        organization_id=body.organization_id,
        full_name=body.full_name,
        external_ref=body.external_ref,
        actor=principal,
    )
    student = await student_service.enroll_student(command, uow=uow)
    return _student_dto_to_response(student)


@students_router.get(
    "",
    response_model=list[StudentSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List students",
    description=(
        "Org Admin (API Contracts §4.3). Not yet tenant-scoped — see this module's own "
        "docstring and `infra/repositories.py`'s (Phase 10.3): `list_all` uses an "
        "unrestricted `TenantRegionScope` pending a system-wide `ScopeResolver` binding. "
        "Also pending the approved RBAC permission matrix — see `enroll_student`'s note."
    ),
)
async def list_students(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.list"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StudentSummaryResponse]:
    students = await student_service.list_students(ListStudentsQuery(), uow=uow)
    return [_student_summary_dto_to_response(student) for student in students]


@students_router.get(
    "/{student_id}",
    response_model=StudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a student by id",
    description=(
        "Org Admin (API Contracts §4.3/§4 uniform CRUD). Pending the approved RBAC "
        "permission matrix — see `enroll_student`'s note."
    ),
)
async def get_student(
    student_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.read"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentResponse:
    student = await student_service.get_student_by_id(
        GetStudentByIdQuery(student_id=student_id), uow=uow
    )
    return _student_dto_to_response(student)


@students_router.patch(
    "/{student_id}",
    response_model=StudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a student's details",
    description=(
        "Org Admin (API Contracts §4 uniform CRUD). Limited to `full_name`/`external_ref` — "
        "see `UpdateStudentRequest`'s docstring for why `status` is not accepted here. "
        "Pending the approved RBAC permission matrix — see `enroll_student`'s note."
    ),
)
async def update_student(
    student_id: str,
    body: UpdateStudentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.update"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentResponse:
    if body.full_name is None and body.external_ref is None:
        raise ValidationError(
            "At least one of 'full_name' or 'external_ref' must be provided.",
            details={"fields": ["full_name", "external_ref"]},
        )

    current = await student_service.get_student_by_id(
        GetStudentByIdQuery(student_id=student_id), uow=uow
    )
    command = UpdateStudentCommand(
        student_id=student_id,
        full_name=body.full_name if body.full_name is not None else current.full_name,
        external_ref=(
            body.external_ref if body.external_ref is not None else current.external_ref
        ),
        actor=principal,
    )
    student = await student_service.update_student(command, uow=uow)
    return _student_dto_to_response(student)


@students_router.post(
    "/{student_id}/status",
    response_model=StudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Transition a student's status",
    description=(
        "Org Admin — body `{status}` -> disable/graduate/transfer -> emits CR-1 revocation "
        "(API Contracts §4.3 line 123 verbatim). `active` is also accepted, reaching "
        "`StudentApplicationService.activate_student` — see `UpdateStudentStatusRequest`'s "
        "docstring. Pending the approved RBAC permission matrix — see `enroll_student`'s "
        "note."
    ),
)
async def update_student_status(
    student_id: str,
    body: UpdateStudentStatusRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.update_status"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentResponse:
    if body.status == "active":
        student = await student_service.activate_student(
            ActivateStudentCommand(student_id=student_id, actor=principal), uow=uow
        )
    elif body.status == "disabled":
        student = await student_service.disable_student(
            DisableStudentCommand(student_id=student_id, actor=principal), uow=uow
        )
    elif body.status == "graduated":
        student = await student_service.graduate_student(
            GraduateStudentCommand(student_id=student_id, actor=principal), uow=uow
        )
    elif body.status == "transferred":
        student = await student_service.transfer_student(
            TransferStudentCommand(student_id=student_id, actor=principal), uow=uow
        )
    else:
        raise ValidationError(
            f"Unsupported status: {body.status!r}", details={"field": "status"}
        )

    return _student_dto_to_response(student)
