"""Application-layer command validators (Backend LLD §4.1's application table: "Contextual
pre-conditions of a use-case"). These check pre-conditions that need repository I/O, which is
exactly why they're an application concern and not a domain one — mirroring
`iam`/`organization`'s identical reasoning (`fleet_device.domain.services`'s own docstring
records why none of these are domain services).

Each pre-check is defense-in-depth over a database-enforced constraint, surfacing a typed
error instead of a raw constraint-violation:

- `ensure_plate_no_available` → `ux_vehicles__org_plate` (Database Design §5.1; per-tenant —
  tenant scoping is injected at the repository layer, `.claude/rules/backend.md` #4).
- `ensure_terminal_id_available` → the global `UX` on `devices.terminal_id` (§5.2).
- `ensure_device_has_no_active_assignment` / `ensure_vehicle_has_no_active_device` → the two
  generated-column unique indexes on `device_assignments` (§5.4). One-active-device-per-
  vehicle is a safety-critical invariant requiring explicit regression tests
  (`.claude/rules/testing.md` #3) — this guard plus the DB index are its two enforcement
  layers (LLD §5.2's placement pattern).
- `ensure_vehicle_exists` → the in-context FK `device_assignments.vehicle_id → vehicles.id`.
"""

from __future__ import annotations

from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.domain.entities import Vehicle
from raad.modules.fleet_device.domain.value_objects import (
    DeviceId,
    TerminalId,
    VehicleId,
)


async def ensure_plate_no_available(uow: FleetDeviceUnitOfWork, plate_no: str) -> None:
    existing = await uow.vehicles.get_by_plate_no(plate_no)
    if existing is not None:
        raise ConflictError(
            f"A vehicle with plate number {plate_no!r} already exists in this organization."
        )


async def ensure_terminal_id_available(
    uow: FleetDeviceUnitOfWork, terminal_id: TerminalId
) -> None:
    existing = await uow.devices.get_by_terminal_id(terminal_id)
    if existing is not None:
        raise ConflictError(f"A device with terminal id {terminal_id} already exists.")


async def ensure_vehicle_exists(
    uow: FleetDeviceUnitOfWork, vehicle_id: VehicleId
) -> Vehicle:
    vehicle = await uow.vehicles.get(vehicle_id)
    if vehicle is None:
        raise NotFoundError(f"Vehicle {vehicle_id} not found.")
    return vehicle


async def ensure_device_has_no_active_assignment(
    uow: FleetDeviceUnitOfWork, device_id: DeviceId
) -> None:
    active = await uow.device_assignments.active_for_device(device_id)
    if active is not None:
        raise ConflictError(
            f"Device {device_id} is already assigned to vehicle {active.vehicle_id} "
            "(one active binding per device, Phase 2 §19)."
        )


async def ensure_vehicle_has_no_active_device(
    uow: FleetDeviceUnitOfWork, vehicle_id: VehicleId
) -> None:
    active = await uow.device_assignments.active_for_vehicle(vehicle_id)
    if active is not None:
        raise ConflictError(
            f"Vehicle {vehicle_id} already has an active device {active.device_id} "
            "(one active device per vehicle, Phase 2 §19)."
        )
