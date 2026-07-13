"""Fleet & Device domain layer (Backend LLD §5; Database Design §5; Phase 2 §19) —
Phase 7.1 scope.

Framework-free: entities/value objects/events/repository interfaces only. No application
services, no infra, no DI — those are later phases. Public surface of this package.

Scope: `Vehicle`, `Device` (owning `Camera` children), and `DeviceAssignment` — exactly the
four Database Design §5 tables. Driver assignment is deliberately absent (device ≠ driver,
Phase 2 §19.1: it lives in `transport_ops`, expressed through trips); connectivity state
(Online/Offline, Phase 2 §21.1) is deliberately absent (runtime state owned by the JT808
service, not this business lifecycle) — see `entities.py`'s module docstring.
"""

from raad.modules.fleet_device.domain.entities import (
    Camera,
    Device,
    DeviceAssignment,
    Vehicle,
)
from raad.modules.fleet_device.domain.repositories import (
    DeviceAssignmentRepository,
    DeviceRepository,
    VehicleRepository,
)
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    CameraId,
    CameraPosition,
    DeviceId,
    DeviceLifecycleState,
    Msisdn,
    OrganizationId,
    TerminalId,
    VehicleId,
    VehicleStatus,
)

__all__ = [
    "AssignmentId",
    "Camera",
    "CameraId",
    "CameraPosition",
    "Device",
    "DeviceAssignment",
    "DeviceAssignmentRepository",
    "DeviceId",
    "DeviceLifecycleState",
    "DeviceRepository",
    "Msisdn",
    "OrganizationId",
    "TerminalId",
    "Vehicle",
    "VehicleId",
    "VehicleRepository",
    "VehicleStatus",
]
