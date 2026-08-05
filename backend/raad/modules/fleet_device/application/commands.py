"""Fleet & Device application commands (Backend LLD §4.2 "intent DTOs"). Immutable request
objects describing what the caller wants done, matching `iam`/`organization`'s exact shape:
every command carries the calling `Principal` as `actor` (the LLD's own contract-skeleton
style — `Command AssignDeviceToVehicle { device_id, vehicle_id, actor }` is implemented
verbatim below), identifiers are plain `str` (converted to value objects inside the service),
and `CameraPosition` is passed as the already-typed domain enum — the same treatment
`RegisterOrganizationCommand.org_type: OrgType` gives an already-parsed enum.

`RegisterDeviceCommand` deliberately has **no auth-key field**: `devices.auth_key_hash` is
nullable (Database Design §5.2) and no approved document specifies the provisioning workflow
for device auth keys (who generates them, how they're hashed, how they reach the terminal —
Phase 2 §12.7 names the control, not the workflow). The column stays NULL until that flow is
designed, rather than inventing one here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raad.core.tenancy.principal import Principal
from raad.modules.fleet_device.domain.value_objects import CameraPosition

# --- Vehicle ------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterVehicleCommand:
    organization_id: str
    plate_no: str
    label: str | None
    capacity: int | None
    actor: Principal


@dataclass(frozen=True)
class ActivateVehicleCommand:
    vehicle_id: str
    actor: Principal


@dataclass(frozen=True)
class DeactivateVehicleCommand:
    vehicle_id: str
    actor: Principal


@dataclass(frozen=True)
class MarkVehicleUnderMaintenanceCommand:
    vehicle_id: str
    actor: Principal


# --- Device -------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterDeviceCommand:
    organization_id: str
    terminal_id: str
    model: str | None
    vendor: str | None
    sim_msisdn: str | None
    imei: str | None
    iccid: str | None
    serial_number: str | None
    actor: Principal


@dataclass(frozen=True)
class ActivateDeviceCommand:
    device_id: str
    actor: Principal


@dataclass(frozen=True)
class SuspendDeviceCommand:
    device_id: str
    actor: Principal


@dataclass(frozen=True)
class ReactivateDeviceCommand:
    device_id: str
    actor: Principal


@dataclass(frozen=True)
class RetireDeviceCommand:
    device_id: str
    actor: Principal


@dataclass(frozen=True)
class RegisterCameraCommand:
    device_id: str
    channel_no: int
    position: CameraPosition
    label: str | None
    actor: Principal


@dataclass(frozen=True)
class RecordDeviceSeenCommand:
    """`docs/architecture/post-f7-production-readiness-roadmap.md` Phase A item A3 — the
    device-gateway's `DeviceOnline`/`DeviceOffline` connectivity events, consumed by
    `events/subscribers.py`. `actor` follows `notifications/events/subscribers.py`'s own
    already-established `SYSTEM_PRINCIPAL` precedent for a broker-driven, non-HTTP caller.
    `is_online` (ADR-0020 §3): `True` for a `DeviceOnline` event, `False` for `DeviceOffline` —
    resolved by the caller (`events/subscribers.py`, which already knows the event type),
    never guessed here."""

    device_id: str
    seen_at: datetime
    is_online: bool
    actor: Principal


# --- Device ↔ Vehicle assignment ----------------------------------------------------------


@dataclass(frozen=True)
class AssignDeviceToVehicleCommand:
    """LLD §4.2 verbatim: `Command AssignDeviceToVehicle { device_id, vehicle_id, actor }`."""

    device_id: str
    vehicle_id: str
    actor: Principal


@dataclass(frozen=True)
class UnassignDeviceCommand:
    device_id: str
    actor: Principal


@dataclass(frozen=True)
class ReassignDeviceCommand:
    """Phase 2 §19.2's reassignment flow: close the current active assignment, open a new one
    against `new_vehicle_id` (LLD §4.2: `handle(ReassignDevice)`)."""

    device_id: str
    new_vehicle_id: str
    actor: Principal


# --- DeviceInventoryItem (ADR-0018) ---------------------------------------------------------


@dataclass(frozen=True)
class ReceiveDeviceInventoryItemCommand:
    """ADR-0018 §2: `POST /device-inventory`."""

    serial_number: str
    imei: str | None
    iccid: str | None
    model: str | None
    vendor: str | None
    actor: Principal


@dataclass(frozen=True)
class AllocateDeviceInventoryItemCommand:
    """ADR-0018 §2: `POST /device-inventory/{id}/allocate` — body `{organization_id}` only.
    `terminal_id` is deliberately absent here: `DeviceInventoryApplicationService.
    allocate_device_inventory_item` derives it from the inventory item's own `serial_number`
    (resolved gap, see that method's own docstring)."""

    inventory_item_id: str
    organization_id: str
    actor: Principal
