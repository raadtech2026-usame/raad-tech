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
- `ensure_imei_available` / `ensure_iccid_available` / `ensure_serial_number_available` →
  the three global `UX`s added by the Device Domain Overhaul architecture review
  (`ux_devices__imei`/`ux_devices__iccid`/`ux_devices__serial_number`) — same shape as
  `ensure_terminal_id_available`, only run when the optional value is actually provided.
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
from raad.modules.fleet_device.domain.entities import Device, DeviceInventoryItem, Vehicle
from raad.modules.fleet_device.domain.value_objects import (
    DeviceId,
    DeviceInventoryState,
    Iccid,
    Imei,
    SerialNumber,
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


async def ensure_imei_available(uow: FleetDeviceUnitOfWork, imei: Imei) -> None:
    existing = await uow.devices.get_by_imei(imei)
    if existing is not None:
        raise ConflictError(f"A device with IMEI {imei} already exists.")


async def ensure_iccid_available(uow: FleetDeviceUnitOfWork, iccid: Iccid) -> None:
    existing = await uow.devices.get_by_iccid(iccid)
    if existing is not None:
        raise ConflictError(f"A device with ICCID {iccid} already exists.")


async def ensure_serial_number_available(
    uow: FleetDeviceUnitOfWork, serial_number: SerialNumber
) -> None:
    existing = await uow.devices.get_by_serial_number(serial_number)
    if existing is not None:
        raise ConflictError(
            f"A device with serial number {serial_number} already exists."
        )


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


async def ensure_inventory_serial_number_available(
    uow: FleetDeviceUnitOfWork, serial_number: SerialNumber
) -> None:
    """ADR-0018: uniqueness within `device_inventory`'s own table only — a separate check from
    `ensure_serial_number_available`'s existing `devices`-table check. Cross-table uniqueness
    (an inventory item's serial number vs. an already-registered `devices` row predating this
    ADR) is not checked at receive time — flagged, not silently invented around; it *is* checked
    at allocation time, when `allocate_device_inventory_item` reuses the existing `devices`-table
    validators before creating the row."""
    existing = await uow.device_inventory.get_by_serial_number(serial_number)
    if existing is not None:
        raise ConflictError(
            f"A device inventory item with serial number {serial_number!r} already exists."
        )


async def ensure_inventory_imei_available(
    uow: FleetDeviceUnitOfWork, imei: Imei
) -> None:
    existing = await uow.device_inventory.get_by_imei(imei)
    if existing is not None:
        raise ConflictError(f"A device inventory item with IMEI {imei} already exists.")


async def ensure_inventory_iccid_available(
    uow: FleetDeviceUnitOfWork, iccid: Iccid
) -> None:
    existing = await uow.device_inventory.get_by_iccid(iccid)
    if existing is not None:
        raise ConflictError(f"A device inventory item with ICCID {iccid} already exists.")


def ensure_inventory_item_allocatable(item: DeviceInventoryItem) -> None:
    """Application-layer guard, distinct from `DeviceInventoryItem.allocate()`'s own
    domain-level idempotent same-state no-op: allocation has the side effect of creating a new
    `devices` row, so a double-submit/retry against an already-`ALLOCATED` item must fail loudly
    here rather than silently reach the aggregate's no-op path and let the service go on to
    create a *second* `devices` row for the same physical item."""
    if item.state != DeviceInventoryState.IN_STOCK:
        raise ConflictError(
            f"Device inventory item {item.id} is not allocatable (state "
            f"{item.state.value!r}, ADR-0018)."
        )


def ensure_same_organization(device: Device, vehicle: Vehicle) -> None:
    """ADR-0021: `assign_device_to_vehicle`/`reassign_device` previously bound a device to a
    vehicle with no check that they belong to the same organization at all — both were merely
    each individually confirmed to exist. A device from one organization bound to a vehicle in
    another is nonsensical regardless of who is asking, independent of the caller's own scope
    (which by itself only proves the caller may act on *each* resource, not that the two
    resources agree with each other)."""
    if device.organization_id != vehicle.organization_id:
        raise ConflictError(
            f"Device {device.id} (organization {device.organization_id}) cannot be assigned "
            f"to vehicle {vehicle.id} (organization {vehicle.organization_id}) — a device may "
            "only be assigned to a vehicle in its own organization."
        )
