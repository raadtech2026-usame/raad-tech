"""Fleet & Device application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models).
DTOs are plain dataclasses — the boundary between the domain's aggregates and any future
API/infra layer, so neither ever depends on the other's internal shape. Mirrors
`organization.application.queries`'s shape exactly.

`DeviceDTO.sim_msisdn` carries the full value (the DTO is an in-process boundary, not a log
line); the "masked in logs" rule (Database Design §5.2) is honored by the `Msisdn` value
object's `repr()` and by whatever the API/logging layers choose to render — not by silently
degrading the read-model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raad.modules.fleet_device.domain.entities import (
    Camera,
    Device,
    DeviceAssignment,
    Vehicle,
)


@dataclass(frozen=True)
class GetVehicleByIdQuery:
    vehicle_id: str


@dataclass(frozen=True)
class ListVehiclesQuery:
    pass


@dataclass(frozen=True)
class GetDeviceByIdQuery:
    device_id: str


@dataclass(frozen=True)
class ListDevicesQuery:
    pass


@dataclass(frozen=True)
class VehicleDTO:
    id: str
    organization_id: str
    plate_no: str
    label: str | None
    capacity: int | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CameraDTO:
    id: str
    channel_no: int
    position: str
    label: str | None


@dataclass(frozen=True)
class DeviceDTO:
    id: str
    organization_id: str
    terminal_id: str
    model: str | None
    vendor: str | None
    sim_msisdn: str | None
    lifecycle_state: str
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime
    cameras: tuple[CameraDTO, ...]


@dataclass(frozen=True)
class DeviceAssignmentDTO:
    id: str
    organization_id: str
    device_id: str
    vehicle_id: str
    assigned_by: str | None
    assigned_at: datetime
    unassigned_at: datetime | None
    is_active: bool


def vehicle_to_dto(vehicle: Vehicle) -> VehicleDTO:
    """Shared mapper — the only place a `Vehicle` aggregate is projected into its DTO."""
    return VehicleDTO(
        id=str(vehicle.id),
        organization_id=str(vehicle.organization_id),
        plate_no=vehicle.plate_no,
        label=vehicle.label,
        capacity=vehicle.capacity,
        status=vehicle.status.value,
        created_at=vehicle.created_at,
        updated_at=vehicle.updated_at,
    )


def camera_to_dto(camera: Camera) -> CameraDTO:
    return CameraDTO(
        id=str(camera.id),
        channel_no=camera.channel_no,
        position=camera.position.value,
        label=camera.label,
    )


def device_to_dto(device: Device) -> DeviceDTO:
    """Shared mapper — the only place a `Device` aggregate is projected into its DTO."""
    return DeviceDTO(
        id=str(device.id),
        organization_id=str(device.organization_id),
        terminal_id=str(device.terminal_id),
        model=device.model,
        vendor=device.vendor,
        sim_msisdn=str(device.sim_msisdn) if device.sim_msisdn is not None else None,
        lifecycle_state=device.lifecycle_state.value,
        last_seen_at=device.last_seen_at,
        created_at=device.created_at,
        updated_at=device.updated_at,
        cameras=tuple(camera_to_dto(camera) for camera in device.cameras),
    )


def assignment_to_dto(assignment: DeviceAssignment) -> DeviceAssignmentDTO:
    """Shared mapper — the only place a `DeviceAssignment` aggregate is projected into its
    DTO."""
    return DeviceAssignmentDTO(
        id=str(assignment.id),
        organization_id=str(assignment.organization_id),
        device_id=str(assignment.device_id),
        vehicle_id=str(assignment.vehicle_id),
        assigned_by=assignment.assigned_by,
        assigned_at=assignment.assigned_at,
        unassigned_at=assignment.unassigned_at,
        is_active=assignment.is_active,
    )
