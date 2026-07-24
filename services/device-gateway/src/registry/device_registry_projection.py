"""`DeviceRegistryProjection` — an in-memory read-model of `fleet_device` devices, updated by
consuming that module's own domain events (`DeviceRegistered`/`DeviceActivated`/`DeviceSuspended`/
`DeviceReactivated`/`DeviceRetired`/`DeviceAssignedToVehicle`/`DeviceUnassignedFromVehicle`/
`DeviceReassigned`) — never by a synchronous cross-service DB read (`.claude/rules/
architecture.md` #3). Vendor-agnostic: keyed by both `terminal_id` (JT/T 808 identity) and
`serial_number` (this platform's LSZ MDVR identity, per ADR-0009's Consequences section noting
`device_registered`'s payload needed an additive `serial_number` field for exactly this purpose),
so any current or future vendor adapter can resolve its own identity string back to
`{device_id, organization_id, vehicle_id}` through the same shared projection.

**Event payload shapes this projection depends on — traced to `backend/raad/modules/fleet_device/
domain/events.py` directly, not guessed:** `DeviceRegistered`'s payload carries `terminal_id`/
`serial_number`; every subsequent lifecycle event (`DeviceActivated`/`DeviceSuspended`/
`DeviceReactivated`/`DeviceRetired`) carries only `{actor_id}` and relies on `aggregate_id` (the
`device_id`) to identify which already-registered record it updates — a record for a device_id
this projection has never seen `DeviceRegistered` for is silently ignored (the projection has
nothing to update; this is expected during a consumer's initial catch-up window, not an error).
`DeviceAssignedToVehicle`/`DeviceUnassignedFromVehicle` carry `device_id` directly in their own
payload (their `aggregate_id` is the *assignment* id, not the device id — `fleet_device`'s own
`events.py` docstring: "Reassignment is an orchestration... performed by the application layer
across two DeviceAssignment aggregates"). `DeviceReassigned`'s `aggregate_id` *is* the device_id,
with `new_vehicle_id` in its payload.

**Authorization join condition — a decision this projection makes, not dictated by any single
document:** a device is considered *provisionable* (usable to authorize a vendor protocol
registration) only when `is_active` (has been `Activated`/`Reactivated`, not `Suspended`/
`Retired`) **and** `vehicle_id is not None` (assigned to a vehicle) — both are required because
every position-reporting handler in this deployable (`vendors.jt808.handlers.location_handler.
LocationHandler`, `vendors.lsz.handlers.position_handler.MdvrPositionHandler`) already requires a
resolved `vehicle_id` before it will publish anything; a device authorized without one would
create sessions no handler could ever use.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeviceRecord:
    device_id: str
    organization_id: str | None
    terminal_id: str | None
    serial_number: str | None
    is_active: bool
    vehicle_id: str | None

    @property
    def is_provisionable(self) -> bool:
        return self.is_active and self.vehicle_id is not None


_ACTIVATING_EVENTS = {"DeviceActivated", "DeviceReactivated"}
_DEACTIVATING_EVENTS = {"DeviceSuspended", "DeviceRetired"}


class DeviceRegistryProjection:
    def __init__(self) -> None:
        self._by_device_id: dict[str, DeviceRecord] = {}
        self._device_id_by_terminal_id: dict[str, str] = {}
        self._device_id_by_serial_number: dict[str, str] = {}

    def apply_event(
        self, *, event_type: str, aggregate_id: str, org_id: str | None, payload: dict
    ) -> None:
        if event_type == "DeviceRegistered":
            self._apply_registered(aggregate_id=aggregate_id, org_id=org_id, payload=payload)
        elif event_type in _ACTIVATING_EVENTS:
            self._set_active(aggregate_id, True)
        elif event_type in _DEACTIVATING_EVENTS:
            self._set_active(aggregate_id, False)
        elif event_type in ("DeviceAssignedToVehicle", "DeviceUnassignedFromVehicle"):
            device_id = payload.get("device_id")
            if device_id:
                record = self._by_device_id.get(device_id)
                if record is not None:
                    record.vehicle_id = (
                        payload.get("vehicle_id")
                        if event_type == "DeviceAssignedToVehicle"
                        else None
                    )
        elif event_type == "DeviceReassigned":
            record = self._by_device_id.get(aggregate_id)
            if record is not None:
                record.vehicle_id = payload.get("new_vehicle_id")

    def _apply_registered(self, *, aggregate_id: str, org_id: str | None, payload: dict) -> None:
        terminal_id = payload.get("terminal_id")
        serial_number = payload.get("serial_number")
        record = DeviceRecord(
            device_id=aggregate_id,
            organization_id=org_id,
            terminal_id=terminal_id,
            serial_number=serial_number,
            is_active=False,
            vehicle_id=None,
        )
        self._by_device_id[aggregate_id] = record
        if terminal_id:
            self._device_id_by_terminal_id[terminal_id] = aggregate_id
        if serial_number:
            self._device_id_by_serial_number[serial_number] = aggregate_id

    def _set_active(self, device_id: str, active: bool) -> None:
        record = self._by_device_id.get(device_id)
        if record is not None:
            record.is_active = active

    def lookup_by_terminal_id(self, terminal_id: str) -> DeviceRecord | None:
        device_id = self._device_id_by_terminal_id.get(terminal_id)
        return self._by_device_id.get(device_id) if device_id else None

    def lookup_by_serial_number(self, serial_number: str) -> DeviceRecord | None:
        device_id = self._device_id_by_serial_number.get(serial_number)
        return self._by_device_id.get(device_id) if device_id else None

    def __len__(self) -> int:
        return len(self._by_device_id)
