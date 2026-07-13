"""HTTP surface of the `fleet_device` module (C3) — Phase 7.4. `vehicles_router` mounts at
`/api/v1/vehicles`, `devices_router` at `/api/v1/devices` (`interfaces/http/api_v1.py`).

Thin controllers only (Backend LLD §16.2): parse the request DTO, call exactly one
application-service method, return the response DTO. No business logic, no repository/
SQLAlchemy access, no aggregate manipulation — every error raised by the application/domain
layers already maps to the standard `ErrorEnvelope` via the global exception handlers.
Mirrors `iam`/`organization.api.routers`'s shape exactly, including the
`require_permission`-pending-RBAC-matrix posture (`interfaces/http/deps.py`): every route is
authorization-gated the same way, so it currently raises `NotImplementedError` (500) rather
than a guessed permission matrix, per API Contracts §4.2's role column and §3.1's layering.

**Endpoints deliberately not implemented** (documented, not silently dropped):
- `GET /vehicles` and `GET /devices` (list) — no listing use-case or scope-filtered query
  exists in the application/repository layers, and API Contracts §4.2's role column requires
  scope-filtering ("+RAAD in scope"), which needs `effective_org_scope` — still pending per
  `interfaces/http/deps.get_scope`. Same deferral as `GET /users` (5.4) and
  `GET /organizations` (6.4).
- `DELETE /vehicles/{id}` / `DELETE /devices/{id}` (uniform-CRUD soft delete, §4 preamble) —
  neither aggregate has soft-delete behavior in the domain (Database Design §9 keeps soft
  delete and business status separate concepts); same deferral as `DELETE /users` (5.4).
- `GET /devices/{id}/status` (connectivity, online/offline) — **approved route, not yet
  implementable**: connectivity is device-plane runtime state (Phase 2 §21.1), owned by the
  JT808 service's session manager, with `devices.last_seen_at` as a durable mirror written by
  a `DeviceOnline`/`DeviceOffline` event consumer. Neither the JT808 service nor that
  consumer exists yet, so `last_seen_at` is always NULL — an endpoint would report every
  device "offline"/unknown, a misleading answer for a safety-relevant surface (flutter rule
  #6's honesty principle applies platform-wide). Implemented alongside the device-plane
  phases instead.
- **Camera registration has an application use-case but no approved endpoint** — API
  Contracts §4.2 lists no camera route, so none is exposed (routes are contract-driven, not
  capability-driven). `RegisterCameraCommand` stays reachable for the future contract
  revision or provisioning flow that documents it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raad.core.errors.exceptions import ValidationError
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import require_permission
from raad.modules.fleet_device.api.deps import (
    get_device_service,
    get_fleet_device_uow,
    get_vehicle_service,
)
from raad.modules.fleet_device.api.schemas import (
    AssignDeviceRequest,
    CameraResponse,
    DeviceAssignmentResponse,
    DeviceResponse,
    ReassignDeviceRequest,
    RegisterDeviceRequest,
    RegisterVehicleRequest,
    UpdateDeviceRequest,
    UpdateVehicleRequest,
    VehicleResponse,
)
from raad.modules.fleet_device.application.commands import (
    ActivateDeviceCommand,
    ActivateVehicleCommand,
    AssignDeviceToVehicleCommand,
    DeactivateVehicleCommand,
    MarkVehicleUnderMaintenanceCommand,
    ReactivateDeviceCommand,
    ReassignDeviceCommand,
    RegisterDeviceCommand,
    RegisterVehicleCommand,
    RetireDeviceCommand,
    SuspendDeviceCommand,
    UnassignDeviceCommand,
)
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.queries import (
    DeviceAssignmentDTO,
    DeviceDTO,
    GetDeviceByIdQuery,
    GetVehicleByIdQuery,
    VehicleDTO,
)
from raad.modules.fleet_device.application.services import (
    DeviceApplicationService,
    VehicleApplicationService,
)

vehicles_router = APIRouter()
devices_router = APIRouter()


def _vehicle_dto_to_response(vehicle: VehicleDTO) -> VehicleResponse:
    return VehicleResponse(
        id=vehicle.id,
        organization_id=vehicle.organization_id,
        plate_no=vehicle.plate_no,
        label=vehicle.label,
        capacity=vehicle.capacity,
        status=vehicle.status,
    )


def _device_dto_to_response(device: DeviceDTO) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        organization_id=device.organization_id,
        terminal_id=device.terminal_id,
        model=device.model,
        vendor=device.vendor,
        sim_msisdn=device.sim_msisdn,
        lifecycle_state=device.lifecycle_state,
        last_seen_at=device.last_seen_at,
        cameras=[
            CameraResponse(
                id=camera.id,
                channel_no=camera.channel_no,
                position=camera.position,
                label=camera.label,
            )
            for camera in device.cameras
        ],
    )


def _assignment_dto_to_response(
    assignment: DeviceAssignmentDTO,
) -> DeviceAssignmentResponse:
    return DeviceAssignmentResponse(
        id=assignment.id,
        organization_id=assignment.organization_id,
        device_id=assignment.device_id,
        vehicle_id=assignment.vehicle_id,
        assigned_by=assignment.assigned_by,
        assigned_at=assignment.assigned_at,
        unassigned_at=assignment.unassigned_at,
        is_active=assignment.is_active,
    )


# --- Vehicles -------------------------------------------------------------------------


@vehicles_router.post(
    "",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new vehicle",
    description=(
        "Org Admin (+RAAD in scope) (API Contracts §4.2). Authorization uses "
        "`require_permission` — pending the approved RBAC permission matrix, so this "
        "currently raises `NotImplementedError` (500) rather than a guessed matrix, "
        "matching `iam`/`organization`'s posture."
    ),
)
async def register_vehicle(
    body: RegisterVehicleRequest,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.vehicles.create"))
    ),
    vehicle_service: VehicleApplicationService = Depends(get_vehicle_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> VehicleResponse:
    command = RegisterVehicleCommand(
        organization_id=body.organization_id,
        plate_no=body.plate_no,
        label=body.label,
        capacity=body.capacity,
        actor=principal,
    )
    vehicle = await vehicle_service.register_vehicle(command, uow=uow)
    return _vehicle_dto_to_response(vehicle)


@vehicles_router.get(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a vehicle by id",
    description=(
        "Org Admin (+RAAD in scope) (API Contracts §4.2/§4 uniform CRUD). Pending the "
        "approved RBAC permission matrix — see `register_vehicle`'s note."
    ),
)
async def get_vehicle(
    vehicle_id: str,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.vehicles.read"))
    ),
    vehicle_service: VehicleApplicationService = Depends(get_vehicle_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> VehicleResponse:
    vehicle = await vehicle_service.get_vehicle_by_id(
        GetVehicleByIdQuery(vehicle_id=vehicle_id), uow=uow
    )
    return _vehicle_dto_to_response(vehicle)


@vehicles_router.patch(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a vehicle's status",
    description=(
        "Org Admin (+RAAD in scope) (API Contracts §4.2/§4 uniform CRUD). Limited to the "
        "`status` transitions the Application layer exposes — see `UpdateVehicleRequest`'s "
        "docstring. Pending the approved RBAC permission matrix — see `register_vehicle`'s "
        "note."
    ),
)
async def update_vehicle(
    vehicle_id: str,
    body: UpdateVehicleRequest,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.vehicles.update"))
    ),
    vehicle_service: VehicleApplicationService = Depends(get_vehicle_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> VehicleResponse:
    if body.status is None:
        raise ValidationError(
            "'status' must be provided.", details={"fields": ["status"]}
        )

    if body.status == "active":
        vehicle = await vehicle_service.activate_vehicle(
            ActivateVehicleCommand(vehicle_id=vehicle_id, actor=principal), uow=uow
        )
    elif body.status == "inactive":
        vehicle = await vehicle_service.deactivate_vehicle(
            DeactivateVehicleCommand(vehicle_id=vehicle_id, actor=principal), uow=uow
        )
    elif body.status == "maintenance":
        vehicle = await vehicle_service.mark_vehicle_under_maintenance(
            MarkVehicleUnderMaintenanceCommand(vehicle_id=vehicle_id, actor=principal),
            uow=uow,
        )
    else:
        raise ValidationError(
            f"Unsupported status: {body.status!r}", details={"field": "status"}
        )

    return _vehicle_dto_to_response(vehicle)


# --- Devices --------------------------------------------------------------------------


@devices_router.post(
    "",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new device",
    description=(
        "Org Admin / Support (API Contracts §4.2). Pending the approved RBAC permission "
        "matrix — see `register_vehicle`'s note."
    ),
)
async def register_device(
    body: RegisterDeviceRequest,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.devices.create"))
    ),
    device_service: DeviceApplicationService = Depends(get_device_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> DeviceResponse:
    command = RegisterDeviceCommand(
        organization_id=body.organization_id,
        terminal_id=body.terminal_id,
        model=body.model,
        vendor=body.vendor,
        sim_msisdn=body.sim_msisdn,
        actor=principal,
    )
    device = await device_service.register_device(command, uow=uow)
    return _device_dto_to_response(device)


@devices_router.get(
    "/{device_id}",
    response_model=DeviceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a device by id",
    description=(
        "Org Admin / Support (API Contracts §4.2/§4 uniform CRUD). Pending the approved "
        "RBAC permission matrix — see `register_vehicle`'s note."
    ),
)
async def get_device(
    device_id: str,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.devices.read"))
    ),
    device_service: DeviceApplicationService = Depends(get_device_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> DeviceResponse:
    device = await device_service.get_device_by_id(
        GetDeviceByIdQuery(device_id=device_id), uow=uow
    )
    return _device_dto_to_response(device)


@devices_router.patch(
    "/{device_id}",
    response_model=DeviceResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a device's lifecycle state",
    description=(
        "Org Admin / Support (API Contracts §4.2: 'lifecycle state'). Limited to the "
        "transitions the Application layer exposes via PATCH — see `UpdateDeviceRequest`'s "
        "docstring; activation and assignment have their own approved behavioral routes. "
        "Pending the approved RBAC permission matrix — see `register_vehicle`'s note."
    ),
)
async def update_device(
    device_id: str,
    body: UpdateDeviceRequest,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.devices.update"))
    ),
    device_service: DeviceApplicationService = Depends(get_device_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> DeviceResponse:
    if body.lifecycle_state is None:
        raise ValidationError(
            "'lifecycle_state' must be provided.",
            details={"fields": ["lifecycle_state"]},
        )

    if body.lifecycle_state == "suspended":
        device = await device_service.suspend_device(
            SuspendDeviceCommand(device_id=device_id, actor=principal), uow=uow
        )
    elif body.lifecycle_state == "activated":
        device = await device_service.reactivate_device(
            ReactivateDeviceCommand(device_id=device_id, actor=principal), uow=uow
        )
    elif body.lifecycle_state == "retired":
        device = await device_service.retire_device(
            RetireDeviceCommand(device_id=device_id, actor=principal), uow=uow
        )
    else:
        raise ValidationError(
            f"Unsupported lifecycle_state: {body.lifecycle_state!r} — 'assigned' is set "
            "only via the assignment routes; initial activation is POST "
            "/devices/{id}/activate.",
            details={"field": "lifecycle_state"},
        )

    return _device_dto_to_response(device)


@devices_router.post(
    "/{device_id}/activate",
    response_model=DeviceResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate a registered device",
    description=(
        "Support/Org Admin — Registered→Activated (API Contracts §4.2 verbatim). Pending "
        "the approved RBAC permission matrix — see `register_vehicle`'s note."
    ),
)
async def activate_device(
    device_id: str,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.devices.activate"))
    ),
    device_service: DeviceApplicationService = Depends(get_device_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> DeviceResponse:
    device = await device_service.activate_device(
        ActivateDeviceCommand(device_id=device_id, actor=principal), uow=uow
    )
    return _device_dto_to_response(device)


@devices_router.post(
    "/{device_id}/assign",
    response_model=DeviceAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a device to a vehicle",
    description=(
        "Org Admin — body `{vehicle_id}` → creates the active `device_assignment` "
        "(API Contracts §4.2 verbatim; one active binding per device & per vehicle, "
        "Phase 2 §19). Pending the approved RBAC permission matrix — see "
        "`register_vehicle`'s note."
    ),
)
async def assign_device(
    device_id: str,
    body: AssignDeviceRequest,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.devices.assign"))
    ),
    device_service: DeviceApplicationService = Depends(get_device_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> DeviceAssignmentResponse:
    assignment = await device_service.assign_device_to_vehicle(
        AssignDeviceToVehicleCommand(
            device_id=device_id, vehicle_id=body.vehicle_id, actor=principal
        ),
        uow=uow,
    )
    return _assignment_dto_to_response(assignment)


@devices_router.post(
    "/{device_id}/reassign",
    response_model=DeviceAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Reassign a device to a different vehicle",
    description=(
        "Org Admin — closes the prior active assignment, opens a new one (API Contracts "
        "§4.2 verbatim; Phase 2 §19.2, emits `DeviceReassigned`). Pending the approved "
        "RBAC permission matrix — see `register_vehicle`'s note."
    ),
)
async def reassign_device(
    device_id: str,
    body: ReassignDeviceRequest,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.devices.reassign"))
    ),
    device_service: DeviceApplicationService = Depends(get_device_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> DeviceAssignmentResponse:
    assignment = await device_service.reassign_device(
        ReassignDeviceCommand(
            device_id=device_id, new_vehicle_id=body.vehicle_id, actor=principal
        ),
        uow=uow,
    )
    return _assignment_dto_to_response(assignment)


@devices_router.post(
    "/{device_id}/unassign",
    response_model=DeviceAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Unassign a device from its vehicle",
    description=(
        "Org Admin (API Contracts §4.2 verbatim). Closes the active assignment; the device "
        "returns to `activated`. Pending the approved RBAC permission matrix — see "
        "`register_vehicle`'s note."
    ),
)
async def unassign_device(
    device_id: str,
    principal: Principal = Depends(
        require_permission(Permission("fleet_device.devices.unassign"))
    ),
    device_service: DeviceApplicationService = Depends(get_device_service),
    uow: FleetDeviceUnitOfWork = Depends(get_fleet_device_uow),
) -> DeviceAssignmentResponse:
    assignment = await device_service.unassign_device(
        UnassignDeviceCommand(device_id=device_id, actor=principal), uow=uow
    )
    return _assignment_dto_to_response(assignment)
