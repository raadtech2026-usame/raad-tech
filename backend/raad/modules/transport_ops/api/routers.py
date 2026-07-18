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

**Phase 10.6: `parents_router` — four routes, matching API Contracts §4.3's `/parents` row**
(line 124: `GET/POST /parents | Org Admin |`, no notes column, unlike `/students`' explicit
`/status` sub-route line):
- `POST /parents` — register
- `GET /parents` — list (same inherited unrestricted-`TenantRegionScope` caveat as
  `list_students`)
- `GET /parents/{id}` — get by id (uniform CRUD)
- `PATCH /parents/{id}` — update `full_name`/`phone`/`status` **together** — unlike
  `Student`'s split between a details-only `PATCH` and a dedicated `POST .../status` route,
  `Parent` has no documented behavioral status sub-route to dispatch to, so `status` folds
  into the uniform `PATCH` instead, mirroring `organization.api.routers.update_organization`/
  `fleet_device.api.routers.update_vehicle`'s status-in-PATCH shape (via
  `UpdateParentRequest`, which — like `iam.api.schemas.UpdateUserRequest` — composes multiple
  optional fields into one request, each independently dispatched, not atomically).
- `DELETE /parents/{id}` not implemented, for the identical reason `DELETE /students/{id}`
  isn't: `Parent` has no soft-delete domain behavior.

**Phase 10.7: Parent<->Student relationship — four routes, no documented API Contracts route
at all** (confirmed by re-reading §4.3 in full: the `/students`/`/parents` rows list no linking
sub-route, unlike `/routes/{id}/stops`'s documented "ordered stops" nesting). Modeled as nested
sub-resource collections under the two existing routers — the one documented precedent in this
same table for a child collection nested under a parent resource — rather than inventing a new
top-level `/student-parents` router:

- `POST /students/{student_id}/parents` — link (`students_router`) — body `{parent_id,
  relationship?, is_primary?}`. Cross-organization/duplicate/not-found rejections all surface
  through the standard error envelope automatically (`DomainError`/`ConflictError`/
  `NotFoundError` from `application/services.py` and `domain/entities.py`).
- `DELETE /students/{student_id}/parents/{parent_id}` — unlink (`students_router`) — the
  **first real `DELETE` in this module**: unlike `Student`/`Parent`'s deferred soft-delete,
  removing a link is a genuine deletion (`domain/entities.py`'s `StudentParent` docstring), so
  this is the correct semantics, not a gap being filled in.
- `GET /students/{student_id}/parents` — list a student's parents (`students_router`).
- `GET /parents/{parent_id}/students` — list a parent's students (`parents_router`).

**Phase 10.8: `drivers_router` — four routes, `/drivers` (Database Design §6.1, ADR-0001).
Flagged, not silently assumed: unlike `/students`/`/parents`, API Contracts §4.3 documents
*no* `/drivers` resource row at all** (re-read in full before implementing — the only
`Driver`-related rows are `/trips/{id}/driver` PATCH, `/trips/{id}/start`, `/trips/{id}/end`,
all `Trip`-aggregate concerns, not `Driver`-profile CRUD). Built anyway, for the same reason
Phase 10.7 built `StudentParent`'s routes despite an identical documentation gap: Database
Design §6.1 unambiguously defines the `drivers` table and ADR-0001 unambiguously assigns it to
this module, the task's own requirements explicitly ask for "FastAPI endpoints", and API
Contracts §4's own preamble establishes a *uniform CRUD pattern per resource* that this
resource simply isn't enumerated under (the `4.3` table is headed "(representative)" — not
exhaustive). This is a real documentation gap, reported here rather than silently decided:

- `POST /drivers` — register (uniform CRUD)
- `GET /drivers` — list (same inherited unrestricted-`TenantRegionScope` caveat as
  `list_students`/`list_parents`)
- `GET /drivers/{id}` — get by id (uniform CRUD)
- `PATCH /drivers/{id}` — update `license_no`/`status` together, mirroring `update_parent`'s
  exact shape (no dedicated behavioral status sub-route is documented for `/drivers` either)
- `DELETE /drivers/{id}` not implemented, for the identical reason `DELETE /students/{id}`/
  `DELETE /parents/{id}` aren't: `Driver` has no soft-delete domain behavior.

**Phase 11: `routes_router` — six routes, matching API Contracts §4.3's `/routes` rows.**
Unlike `Driver`/`StudentParent`, this phase's core routes **are** documented (line 125:
`GET/POST /routes | Org Admin |`; line 126: `GET/POST /routes/{id}/stops | Org Admin | ordered
stops`) — no documentation gap for these six:

- `POST /routes` — create (the doc's uniform "`GET/POST /routes`" create half)
- `GET /routes` — list (the doc's uniform "`GET/POST /routes`" list half; same inherited
  unrestricted-`TenantRegionScope` caveat as `list_students`/`list_parents`/`list_drivers`)
- `GET /routes/{id}` — get by id (uniform CRUD; embeds the route's ordered stops)
- `PATCH /routes/{id}` — update `name`/`status` together, mirroring `update_parent`'s exact
  shape (no dedicated behavioral status sub-route is documented for `/routes` either, and no
  `archived` status value exists to dispatch to — see `domain/entities.py`'s module docstring)
- `POST /routes/{route_id}/stops` — add a stop (API Contracts §4.3 line 126 verbatim: "ordered
  stops"). Returns the created `StopResponse`, mirroring `StudentParentLinkResponse`'s
  "POST-to-a-nested-collection returns the created child" shape (Phase 10.7) rather than the
  whole parent — the closer precedent here than `fleet_device`'s `register_camera` (which has
  no HTTP route at all to set a response-shape precedent from).
- `GET /routes/{route_id}/stops` — list a route's stops, already ordered by `sequence_no`
  (`domain/entities.py`'s `Route.stops` property).

**Documentation gap encountered and flagged, not silently decided:** API Contracts §4.3 line
126 documents only `GET/POST /routes/{id}/stops` for the stops sub-resource — no route exists
for updating, removing, or reordering an individual stop. `Route.remove_stop`/`Route.move_stop`
and their application-service/command counterparts (`application/services.py`,
`application/commands.py`) are fully implemented and unit-tested, but **no HTTP endpoint is
exposed for them this phase** — mirroring `fleet_device.api.routers`'s identical restraint for
`RegisterCameraCommand` ("routes are contract-driven, not capability-driven"). A future API
Contracts revision that documents `PATCH`/`DELETE /routes/{route_id}/stops/{stop_id}` can wire
these straight through with no domain/application change.

**Endpoints deliberately not implemented:**
- `DELETE /routes/{id}` (uniform-CRUD soft delete, §4 preamble) — `Route` has no soft-delete
  domain behavior, the identical deferral `DELETE /students/{id}`/`DELETE /parents/{id}`/
  `DELETE /drivers/{id}` already apply.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raad.core.errors.exceptions import ValidationError
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import require_permission
from raad.modules.transport_ops.api.deps import (
    get_driver_service,
    get_parent_service,
    get_route_service,
    get_student_parent_service,
    get_student_service,
    get_transport_ops_uow,
)
from raad.modules.transport_ops.api.schemas import (
    AddStopToRouteRequest,
    CreateRouteRequest,
    DriverResponse,
    DriverSummaryResponse,
    EnrollStudentRequest,
    LinkParentToStudentRequest,
    ParentForStudentResponse,
    ParentResponse,
    ParentSummaryResponse,
    RegisterDriverRequest,
    RegisterParentRequest,
    RouteResponse,
    RouteSummaryResponse,
    StopResponse,
    StudentForParentResponse,
    StudentParentLinkResponse,
    StudentResponse,
    StudentSummaryResponse,
    UpdateDriverRequest,
    UpdateParentRequest,
    UpdateRouteRequest,
    UpdateStudentRequest,
    UpdateStudentStatusRequest,
)
from raad.modules.transport_ops.application.commands import (
    ActivateDriverCommand,
    ActivateParentCommand,
    ActivateRouteCommand,
    ActivateStudentCommand,
    AddStopToRouteCommand,
    CreateRouteCommand,
    DisableDriverCommand,
    DisableParentCommand,
    DisableRouteCommand,
    DisableStudentCommand,
    EnrollStudentCommand,
    GraduateStudentCommand,
    LinkParentToStudentCommand,
    RegisterDriverCommand,
    RegisterParentCommand,
    TransferStudentCommand,
    UnlinkParentFromStudentCommand,
    UpdateDriverCommand,
    UpdateParentCommand,
    UpdateRouteCommand,
    UpdateStudentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    DriverDTO,
    DriverSummaryDTO,
    GetDriverByIdQuery,
    GetParentByIdQuery,
    GetRouteByIdQuery,
    GetStudentByIdQuery,
    ListDriversQuery,
    ListParentsForStudentQuery,
    ListParentsQuery,
    ListRoutesQuery,
    ListStopsForRouteQuery,
    ListStudentsForParentQuery,
    ListStudentsQuery,
    ParentDTO,
    ParentForStudentDTO,
    ParentSummaryDTO,
    RouteDTO,
    RouteSummaryDTO,
    StopDTO,
    StudentDTO,
    StudentForParentDTO,
    StudentParentDTO,
    StudentSummaryDTO,
)
from raad.modules.transport_ops.application.services import (
    DriverApplicationService,
    ParentApplicationService,
    RouteApplicationService,
    StudentApplicationService,
    StudentParentApplicationService,
)

students_router = APIRouter()
parents_router = APIRouter()
routes_router = APIRouter()
trips_router = APIRouter()
drivers_router = APIRouter()


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


def _parent_dto_to_response(parent: ParentDTO) -> ParentResponse:
    return ParentResponse(
        id=parent.id,
        organization_id=parent.organization_id,
        user_id=parent.user_id,
        full_name=parent.full_name,
        phone=parent.phone,
        status=parent.status,
    )


def _parent_summary_dto_to_response(
    parent: ParentSummaryDTO,
) -> ParentSummaryResponse:
    return ParentSummaryResponse(
        id=parent.id, full_name=parent.full_name, status=parent.status
    )


def _student_parent_dto_to_response(
    link: StudentParentDTO,
) -> StudentParentLinkResponse:
    return StudentParentLinkResponse(
        student_id=link.student_id,
        parent_id=link.parent_id,
        relationship=link.relationship,
        is_primary=link.is_primary,
    )


def _parent_for_student_dto_to_response(
    dto: ParentForStudentDTO,
) -> ParentForStudentResponse:
    return ParentForStudentResponse(
        parent_id=dto.parent_id,
        full_name=dto.full_name,
        phone=dto.phone,
        status=dto.status,
        relationship=dto.relationship,
        is_primary=dto.is_primary,
    )


def _student_for_parent_dto_to_response(
    dto: StudentForParentDTO,
) -> StudentForParentResponse:
    return StudentForParentResponse(
        student_id=dto.student_id,
        full_name=dto.full_name,
        status=dto.status,
        relationship=dto.relationship,
        is_primary=dto.is_primary,
    )


def _driver_dto_to_response(driver: DriverDTO) -> DriverResponse:
    return DriverResponse(
        id=driver.id,
        organization_id=driver.organization_id,
        user_id=driver.user_id,
        license_no=driver.license_no,
        status=driver.status,
    )


def _driver_summary_dto_to_response(
    driver: DriverSummaryDTO,
) -> DriverSummaryResponse:
    return DriverSummaryResponse(
        id=driver.id, license_no=driver.license_no, status=driver.status
    )


def _stop_dto_to_response(stop: StopDTO) -> StopResponse:
    return StopResponse(
        id=stop.id,
        name=stop.name,
        latitude=stop.latitude,
        longitude=stop.longitude,
        sequence_no=stop.sequence_no,
        geofence_radius_m=stop.geofence_radius_m,
    )


def _route_dto_to_response(route: RouteDTO) -> RouteResponse:
    return RouteResponse(
        id=route.id,
        organization_id=route.organization_id,
        name=route.name,
        status=route.status,
        stops=[_stop_dto_to_response(stop) for stop in route.stops],
    )


def _route_summary_dto_to_response(route: RouteSummaryDTO) -> RouteSummaryResponse:
    return RouteSummaryResponse(id=route.id, name=route.name, status=route.status)


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


@parents_router.post(
    "",
    response_model=ParentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new parent",
    description=(
        "Org Admin (API Contracts §4.3). Authorization uses `require_permission` — pending "
        "the approved RBAC permission matrix, so this currently raises `NotImplementedError` "
        "(500) rather than a guessed matrix, matching `enroll_student`'s posture."
    ),
)
async def register_parent(
    body: RegisterParentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.create"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentResponse:
    command = RegisterParentCommand(
        organization_id=body.organization_id,
        user_id=body.user_id,
        full_name=body.full_name,
        phone=body.phone,
        actor=principal,
    )
    parent = await parent_service.register_parent(command, uow=uow)
    return _parent_dto_to_response(parent)


@parents_router.get(
    "",
    response_model=list[ParentSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List parents",
    description=(
        "Org Admin (API Contracts §4.3). Not yet tenant-scoped — same inherited caveat as "
        "`list_students`; see this module's own docstring and `infra/repositories.py`'s "
        "(Phase 10.3). Also pending the approved RBAC permission matrix."
    ),
)
async def list_parents(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.list"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[ParentSummaryResponse]:
    parents = await parent_service.list_parents(ListParentsQuery(), uow=uow)
    return [_parent_summary_dto_to_response(parent) for parent in parents]


@parents_router.get(
    "/{parent_id}",
    response_model=ParentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a parent by id",
    description=(
        "Org Admin (API Contracts §4.3/§4 uniform CRUD). Pending the approved RBAC "
        "permission matrix — see `register_parent`'s note."
    ),
)
async def get_parent(
    parent_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.read"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentResponse:
    parent = await parent_service.get_parent_by_id(
        GetParentByIdQuery(parent_id=parent_id), uow=uow
    )
    return _parent_dto_to_response(parent)


@parents_router.patch(
    "/{parent_id}",
    response_model=ParentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a parent's details and/or status",
    description=(
        "Org Admin (API Contracts §4 uniform CRUD). Composes `full_name`/`phone` (dispatched "
        "to `update_parent`) and `status` (dispatched to `activate_parent`/`disable_parent`) "
        "in one request, each independently — not atomically — mirroring "
        "`iam.api.routers.update_user`'s identical composition. See `UpdateParentRequest`'s "
        "docstring for why `status` is folded in here rather than a dedicated route, unlike "
        "`Student`. Pending the approved RBAC permission matrix."
    ),
)
async def update_parent(
    parent_id: str,
    body: UpdateParentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.update"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentResponse:
    if body.full_name is None and body.phone is None and body.status is None:
        raise ValidationError(
            "At least one of 'full_name', 'phone', or 'status' must be provided.",
            details={"fields": ["full_name", "phone", "status"]},
        )

    parent: ParentDTO | None = None

    if body.full_name is not None or body.phone is not None:
        current = await parent_service.get_parent_by_id(
            GetParentByIdQuery(parent_id=parent_id), uow=uow
        )
        command = UpdateParentCommand(
            parent_id=parent_id,
            full_name=(
                body.full_name if body.full_name is not None else current.full_name
            ),
            phone=body.phone if body.phone is not None else current.phone,
            actor=principal,
        )
        parent = await parent_service.update_parent(command, uow=uow)

    if body.status is not None:
        if body.status == "active":
            parent = await parent_service.activate_parent(
                ActivateParentCommand(parent_id=parent_id, actor=principal), uow=uow
            )
        elif body.status == "inactive":
            parent = await parent_service.disable_parent(
                DisableParentCommand(parent_id=parent_id, actor=principal), uow=uow
            )
        else:
            raise ValidationError(
                f"Unsupported status: {body.status!r}", details={"field": "status"}
            )

    if parent is None:
        # Guaranteed not to happen by the "at least one field" guard above — an explicit
        # raise rather than `assert`, matching `iam.api.routers.update_user`'s identical
        # invariant-holds-regardless-of-interpreter-flags reasoning.
        raise RuntimeError(
            "update_parent: no field was processed despite the guard above."
        )
    return _parent_dto_to_response(parent)


@students_router.post(
    "/{student_id}/parents",
    response_model=StudentParentLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link a parent to a student",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.7 — see `routers.py`'s "
        "module docstring). Rejects cross-organization links (`DomainError`) and duplicate "
        "links (`ConflictError`, both from `StudentParent.link`/`application/validators.py`). "
        "Pending the approved RBAC permission matrix — see `enroll_student`'s note."
    ),
)
async def link_parent_to_student(
    student_id: str,
    body: LinkParentToStudentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_parents.create"))
    ),
    student_parent_service: StudentParentApplicationService = Depends(
        get_student_parent_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentParentLinkResponse:
    command = LinkParentToStudentCommand(
        student_id=student_id,
        parent_id=body.parent_id,
        relationship=body.relationship,
        is_primary=body.is_primary,
        actor=principal,
    )
    link = await student_parent_service.link_parent_to_student(command, uow=uow)
    return _student_parent_dto_to_response(link)


@students_router.delete(
    "/{student_id}/parents/{parent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a parent-student link",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.7). A real deletion, unlike "
        "every other `DELETE` in this module (both currently unimplemented, see "
        "`StudentParent`'s docstring for why this one differs). Pending the approved RBAC "
        "permission matrix."
    ),
)
async def unlink_parent_from_student(
    student_id: str,
    parent_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_parents.delete"))
    ),
    student_parent_service: StudentParentApplicationService = Depends(
        get_student_parent_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> None:
    command = UnlinkParentFromStudentCommand(
        student_id=student_id, parent_id=parent_id, actor=principal
    )
    await student_parent_service.unlink_parent_from_student(command, uow=uow)


@students_router.get(
    "/{student_id}/parents",
    response_model=list[ParentForStudentResponse],
    status_code=status.HTTP_200_OK,
    summary="List a student's linked parents",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.7). Pending the approved "
        "RBAC permission matrix."
    ),
)
async def list_parents_for_student(
    student_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_parents.list"))
    ),
    student_parent_service: StudentParentApplicationService = Depends(
        get_student_parent_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[ParentForStudentResponse]:
    results = await student_parent_service.list_parents_for_student(
        ListParentsForStudentQuery(student_id=student_id), uow=uow
    )
    return [_parent_for_student_dto_to_response(dto) for dto in results]


@parents_router.get(
    "/{parent_id}/students",
    response_model=list[StudentForParentResponse],
    status_code=status.HTTP_200_OK,
    summary="List a parent's linked students",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.7). Pending the approved "
        "RBAC permission matrix."
    ),
)
async def list_students_for_parent(
    parent_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_parents.list"))
    ),
    student_parent_service: StudentParentApplicationService = Depends(
        get_student_parent_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StudentForParentResponse]:
    results = await student_parent_service.list_students_for_parent(
        ListStudentsForParentQuery(parent_id=parent_id), uow=uow
    )
    return [_student_for_parent_dto_to_response(dto) for dto in results]


@drivers_router.post(
    "",
    response_model=DriverResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new driver",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.8 — see this module's own "
        "docstring for the full gap: Database Design §6.1/ADR-0001 define the `drivers` table "
        "and its ownership unambiguously, but API Contracts §4.3 lists no `/drivers` resource "
        "row). Authorization uses `require_permission` — pending the approved RBAC permission "
        "matrix, so this currently raises `NotImplementedError` (500) rather than a guessed "
        "matrix, matching `enroll_student`'s posture."
    ),
)
async def register_driver(
    body: RegisterDriverRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.drivers.create"))
    ),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> DriverResponse:
    command = RegisterDriverCommand(
        organization_id=body.organization_id,
        user_id=body.user_id,
        license_no=body.license_no,
        actor=principal,
    )
    driver = await driver_service.register_driver(command, uow=uow)
    return _driver_dto_to_response(driver)


@drivers_router.get(
    "",
    response_model=list[DriverSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List drivers",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.8, see this module's own "
        "docstring). Not yet tenant-scoped — same inherited caveat as `list_students`/"
        "`list_parents`. Also pending the approved RBAC permission matrix."
    ),
)
async def list_drivers(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.drivers.list"))
    ),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[DriverSummaryResponse]:
    drivers = await driver_service.list_drivers(ListDriversQuery(), uow=uow)
    return [_driver_summary_dto_to_response(driver) for driver in drivers]


@drivers_router.get(
    "/{driver_id}",
    response_model=DriverResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a driver by id",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.8, see this module's own "
        "docstring). Pending the approved RBAC permission matrix — see `register_driver`'s "
        "note."
    ),
)
async def get_driver(
    driver_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.drivers.read"))
    ),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> DriverResponse:
    driver = await driver_service.get_driver_by_id(
        GetDriverByIdQuery(driver_id=driver_id), uow=uow
    )
    return _driver_dto_to_response(driver)


@drivers_router.patch(
    "/{driver_id}",
    response_model=DriverResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a driver's details and/or status",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.8, see this module's own "
        "docstring). Composes `license_no` (dispatched to `update_driver`) and `status` "
        "(dispatched to `activate_driver`/`disable_driver`) in one request, each "
        "independently — not atomically — mirroring `update_parent`'s identical composition. "
        "Pending the approved RBAC permission matrix."
    ),
)
async def update_driver(
    driver_id: str,
    body: UpdateDriverRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.drivers.update"))
    ),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> DriverResponse:
    if body.license_no is None and body.status is None:
        raise ValidationError(
            "At least one of 'license_no' or 'status' must be provided.",
            details={"fields": ["license_no", "status"]},
        )

    driver: DriverDTO | None = None

    if body.license_no is not None:
        command = UpdateDriverCommand(
            driver_id=driver_id,
            license_no=body.license_no,
            actor=principal,
        )
        driver = await driver_service.update_driver(command, uow=uow)

    if body.status is not None:
        if body.status == "active":
            driver = await driver_service.activate_driver(
                ActivateDriverCommand(driver_id=driver_id, actor=principal), uow=uow
            )
        elif body.status == "inactive":
            driver = await driver_service.disable_driver(
                DisableDriverCommand(driver_id=driver_id, actor=principal), uow=uow
            )
        else:
            raise ValidationError(
                f"Unsupported status: {body.status!r}", details={"field": "status"}
            )

    if driver is None:
        # Guaranteed not to happen by the "at least one field" guard above — an explicit
        # raise rather than `assert`, matching `update_parent`'s identical
        # invariant-holds-regardless-of-interpreter-flags reasoning.
        raise RuntimeError(
            "update_driver: no field was processed despite the guard above."
        )
    return _driver_dto_to_response(driver)


@routes_router.post(
    "",
    response_model=RouteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new route",
    description=(
        "Org Admin (API Contracts §4.3 line 125). Authorization uses `require_permission` — "
        "pending the approved RBAC permission matrix, so this currently raises "
        "`NotImplementedError` (500) rather than a guessed matrix, matching "
        "`enroll_student`'s posture."
    ),
)
async def create_route(
    body: CreateRouteRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.create"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> RouteResponse:
    command = CreateRouteCommand(
        organization_id=body.organization_id,
        name=body.name,
        actor=principal,
    )
    route = await route_service.create_route(command, uow=uow)
    return _route_dto_to_response(route)


@routes_router.get(
    "",
    response_model=list[RouteSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List routes",
    description=(
        "Org Admin (API Contracts §4.3 line 125). Not yet tenant-scoped — same inherited "
        "caveat as `list_students`/`list_parents`/`list_drivers`. Also pending the approved "
        "RBAC permission matrix."
    ),
)
async def list_routes(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.list"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[RouteSummaryResponse]:
    routes = await route_service.list_routes(ListRoutesQuery(), uow=uow)
    return [_route_summary_dto_to_response(route) for route in routes]


@routes_router.get(
    "/{route_id}",
    response_model=RouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a route by id",
    description=(
        "Org Admin (API Contracts §4.3/§4 uniform CRUD). Embeds the route's ordered stops. "
        "Pending the approved RBAC permission matrix — see `create_route`'s note."
    ),
)
async def get_route(
    route_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.read"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> RouteResponse:
    route = await route_service.get_route_by_id(
        GetRouteByIdQuery(route_id=route_id), uow=uow
    )
    return _route_dto_to_response(route)


@routes_router.patch(
    "/{route_id}",
    response_model=RouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a route's details and/or status",
    description=(
        "Org Admin (API Contracts §4 uniform CRUD). Composes `name` (dispatched to "
        "`update_route`) and `status` (dispatched to `activate_route`/`disable_route`) in one "
        "request, each independently — not atomically — mirroring `update_parent`'s identical "
        "composition. No `archived` status value exists to dispatch to (Database Design §6.5's "
        "enum is exhaustively `active`/`inactive`, `domain/entities.py`'s module docstring). "
        "Pending the approved RBAC permission matrix."
    ),
)
async def update_route(
    route_id: str,
    body: UpdateRouteRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.update"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> RouteResponse:
    if body.name is None and body.status is None:
        raise ValidationError(
            "At least one of 'name' or 'status' must be provided.",
            details={"fields": ["name", "status"]},
        )

    route: RouteDTO | None = None

    if body.name is not None:
        command = UpdateRouteCommand(
            route_id=route_id,
            name=body.name,
            actor=principal,
        )
        route = await route_service.update_route(command, uow=uow)

    if body.status is not None:
        if body.status == "active":
            route = await route_service.activate_route(
                ActivateRouteCommand(route_id=route_id, actor=principal), uow=uow
            )
        elif body.status == "inactive":
            route = await route_service.disable_route(
                DisableRouteCommand(route_id=route_id, actor=principal), uow=uow
            )
        else:
            raise ValidationError(
                f"Unsupported status: {body.status!r}", details={"field": "status"}
            )

    if route is None:
        # Guaranteed not to happen by the "at least one field" guard above — an explicit
        # raise rather than `assert`, matching `update_parent`'s identical
        # invariant-holds-regardless-of-interpreter-flags reasoning.
        raise RuntimeError(
            "update_route: no field was processed despite the guard above."
        )
    return _route_dto_to_response(route)


@routes_router.post(
    "/{route_id}/stops",
    response_model=StopResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a stop to a route",
    description=(
        "Org Admin — 'ordered stops' (API Contracts §4.3 line 126 verbatim). Rejects a "
        "duplicate `sequence_no` (`ConflictError`) and out-of-range coordinates/sequence "
        "(`DomainError`), both from `Route.add_stop` (`domain/entities.py`). Pending the "
        "approved RBAC permission matrix — see `create_route`'s note."
    ),
)
async def add_stop_to_route(
    route_id: str,
    body: AddStopToRouteRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.stops.create"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StopResponse:
    command = AddStopToRouteCommand(
        route_id=route_id,
        name=body.name,
        latitude=body.latitude,
        longitude=body.longitude,
        sequence_no=body.sequence_no,
        geofence_radius_m=body.geofence_radius_m,
        actor=principal,
    )
    stop = await route_service.add_stop_to_route(command, uow=uow)
    return _stop_dto_to_response(stop)


@routes_router.get(
    "/{route_id}/stops",
    response_model=list[StopResponse],
    status_code=status.HTTP_200_OK,
    summary="List a route's stops in order",
    description=(
        "Org Admin — 'ordered stops' (API Contracts §4.3 line 126 verbatim). Always sorted by "
        "`sequence_no` (`domain/entities.py`'s `Route.stops` property). Pending the approved "
        "RBAC permission matrix — see `create_route`'s note."
    ),
)
async def list_stops_for_route(
    route_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.stops.list"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StopResponse]:
    stops = await route_service.list_stops_for_route(
        ListStopsForRouteQuery(route_id=route_id), uow=uow
    )
    return [_stop_dto_to_response(stop) for stop in stops]
