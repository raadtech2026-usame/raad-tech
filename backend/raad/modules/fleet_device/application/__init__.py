"""Fleet & Device application layer (Backend LLD §4) — Phase 7.2 scope.

Orchestration only: loads aggregates via repositories bound to `FleetDeviceUnitOfWork`,
invokes domain behavior, records the resulting `DomainEvent`s, commits, and returns a DTO. No
FastAPI/SQLAlchemy, no infra, no business rules (those live in `modules/fleet_device/domain`).
Public surface of this package.
"""

from raad.modules.fleet_device.application.commands import (
    ActivateDeviceCommand,
    ActivateVehicleCommand,
    AssignDeviceToVehicleCommand,
    DeactivateVehicleCommand,
    MarkVehicleUnderMaintenanceCommand,
    ReactivateDeviceCommand,
    ReassignDeviceCommand,
    RegisterCameraCommand,
    RegisterDeviceCommand,
    RegisterVehicleCommand,
    RetireDeviceCommand,
    SuspendDeviceCommand,
    UnassignDeviceCommand,
)
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.queries import (
    CameraDTO,
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

__all__ = [
    "ActivateDeviceCommand",
    "ActivateVehicleCommand",
    "AssignDeviceToVehicleCommand",
    "CameraDTO",
    "DeactivateVehicleCommand",
    "DeviceApplicationService",
    "DeviceAssignmentDTO",
    "DeviceDTO",
    "FleetDeviceUnitOfWork",
    "GetDeviceByIdQuery",
    "GetVehicleByIdQuery",
    "MarkVehicleUnderMaintenanceCommand",
    "ReactivateDeviceCommand",
    "ReassignDeviceCommand",
    "RegisterCameraCommand",
    "RegisterDeviceCommand",
    "RegisterVehicleCommand",
    "RetireDeviceCommand",
    "SuspendDeviceCommand",
    "UnassignDeviceCommand",
    "VehicleApplicationService",
    "VehicleDTO",
]
