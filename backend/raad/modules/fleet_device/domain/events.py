"""Domain events for the `fleet_device` module (Backend LLD §5.1/§10.3; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Each factory returns the shared
`DomainEvent` envelope (`core.events.base`) — the existing abstraction, not a parallel one —
populated with `fleet_device`-specific `event_type`/`aggregate_type`/`payload`. Identical
shape to `organization.domain.events`.

Factories take primitive values (ids/enums as `str`), never the aggregate objects themselves —
events must be serializable (they land in `outbox.payload_json`, Database Design §8.8) and this
also avoids a circular import with `entities.py` (which calls these factories).

`DeviceReassigned` is the one event name the approved documentation states verbatim
(Phase 2 §19.2: "Emits `DeviceReassigned`"). Reassignment is an *orchestration* — close the
current active assignment, open a new one (Backend LLD §5.2 invariant) — performed by the
application layer across two `DeviceAssignment` aggregates, so its factory is called by that
layer (a later phase), not by any single aggregate here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from raad.core.events.base import DomainEvent
from raad.core.ids.generator import generate_ulid


def _new_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    org_id: str | None,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> DomainEvent:
    return DomainEvent(
        event_id=generate_ulid(),
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=org_id,
        correlation_id=None,
        payload=payload,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )


# --- Vehicle ------------------------------------------------------------------------------


def vehicle_registered(
    *,
    vehicle_id: str,
    organization_id: str,
    plate_no: str,
    label: str | None,
    capacity: int | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="VehicleRegistered",
        aggregate_type="Vehicle",
        aggregate_id=vehicle_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "plate_no": plate_no,
            "label": label,
            "capacity": capacity,
            "actor_id": actor_id,
        },
    )


def vehicle_activated(
    *,
    vehicle_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="VehicleActivated",
        aggregate_type="Vehicle",
        aggregate_id=vehicle_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def vehicle_deactivated(
    *,
    vehicle_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="VehicleDeactivated",
        aggregate_type="Vehicle",
        aggregate_id=vehicle_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def vehicle_marked_under_maintenance(
    *,
    vehicle_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="VehicleMarkedUnderMaintenance",
        aggregate_type="Vehicle",
        aggregate_id=vehicle_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


# --- Device -------------------------------------------------------------------------------


def device_registered(
    *,
    device_id: str,
    organization_id: str,
    terminal_id: str,
    model: str | None,
    vendor: str | None,
    occurred_at: datetime,
    actor_id: str | None,
    serial_number: str | None = None,
    inventory_id: str | None = None,
) -> DomainEvent:
    """`serial_number` (additive, default `None` so any other call site stays source-compatible)
    was added alongside the already-present `terminal_id` for a device-plane consumer that keys
    on this vendor's own device-identity string rather than a JT/T-808-style terminal id — see
    `docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md`'s "Consequences" section:
    a local device-registry projection resolving `serial_number -> {device_id, vehicle_id,
    organization_id}` needs this field on the event, and it was missing until this change.
    `inventory_id` (ADR-0018, same additive/default-`None` treatment) is populated only when
    this device was created via `POST /device-inventory/{id}/allocate`."""
    return _new_event(
        event_type="DeviceRegistered",
        aggregate_type="Device",
        aggregate_id=device_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "terminal_id": terminal_id,
            "serial_number": serial_number,
            "model": model,
            "vendor": vendor,
            "actor_id": actor_id,
            "inventory_id": inventory_id,
        },
    )


def device_activated(
    *, device_id: str, organization_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="DeviceActivated",
        aggregate_type="Device",
        aggregate_id=device_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def device_suspended(
    *, device_id: str, organization_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="DeviceSuspended",
        aggregate_type="Device",
        aggregate_id=device_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def device_reactivated(
    *, device_id: str, organization_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="DeviceReactivated",
        aggregate_type="Device",
        aggregate_id=device_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def device_retired(
    *, device_id: str, organization_id: str, occurred_at: datetime, actor_id: str | None
) -> DomainEvent:
    return _new_event(
        event_type="DeviceRetired",
        aggregate_type="Device",
        aggregate_id=device_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"actor_id": actor_id},
    )


def camera_registered(
    *,
    camera_id: str,
    device_id: str,
    organization_id: str,
    channel_no: int,
    position: str,
    label: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="CameraRegistered",
        aggregate_type="Device",
        aggregate_id=device_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "camera_id": camera_id,
            "channel_no": channel_no,
            "position": position,
            "label": label,
            "actor_id": actor_id,
        },
    )


def camera_updated(
    *,
    camera_id: str,
    device_id: str,
    organization_id: str,
    position: str,
    label: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """ADR-0032: an Org Admin/RAAD-staff correction of a discovered channel's role/label —
    mirrors `camera_registered`'s exact shape (same aggregate, same payload keys minus
    `channel_no`, which `update_camera` never changes)."""
    return _new_event(
        event_type="CameraUpdated",
        aggregate_type="Device",
        aggregate_id=device_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "camera_id": camera_id,
            "position": position,
            "label": label,
            "actor_id": actor_id,
        },
    )


# --- DeviceAssignment ---------------------------------------------------------------------


def device_assigned_to_vehicle(
    *,
    assignment_id: str,
    device_id: str,
    vehicle_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="DeviceAssignedToVehicle",
        aggregate_type="DeviceAssignment",
        aggregate_id=assignment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "device_id": device_id,
            "vehicle_id": vehicle_id,
            "actor_id": actor_id,
        },
    )


def device_unassigned_from_vehicle(
    *,
    assignment_id: str,
    device_id: str,
    vehicle_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    return _new_event(
        event_type="DeviceUnassignedFromVehicle",
        aggregate_type="DeviceAssignment",
        aggregate_id=assignment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "device_id": device_id,
            "vehicle_id": vehicle_id,
            "actor_id": actor_id,
        },
    )


def device_reassigned(
    *,
    device_id: str,
    organization_id: str,
    old_vehicle_id: str,
    new_vehicle_id: str,
    old_assignment_id: str,
    new_assignment_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """Phase 2 §19.2's explicitly-named event: device moved to a different vehicle (close old
    assignment + open new one). Recorded by the application-layer reassignment use-case (a
    later phase), which is the only place both assignments are in hand."""
    return _new_event(
        event_type="DeviceReassigned",
        aggregate_type="Device",
        aggregate_id=device_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "old_vehicle_id": old_vehicle_id,
            "new_vehicle_id": new_vehicle_id,
            "old_assignment_id": old_assignment_id,
            "new_assignment_id": new_assignment_id,
            "actor_id": actor_id,
        },
    )


# --- DeviceInventoryItem (ADR-0018) -------------------------------------------------------


def device_inventory_item_received(
    *,
    inventory_item_id: str,
    serial_number: str,
    imei: str | None,
    iccid: str | None,
    model: str | None,
    vendor: str | None,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """Platform-scoped — `org_id=None` (ADR-0018: `device_inventory` carries no
    `organization_id` at all, unlike every other event in this module)."""
    return _new_event(
        event_type="DeviceInventoryItemReceived",
        aggregate_type="DeviceInventoryItem",
        aggregate_id=inventory_item_id,
        org_id=None,
        occurred_at=occurred_at,
        payload={
            "serial_number": serial_number,
            "imei": imei,
            "iccid": iccid,
            "model": model,
            "vendor": vendor,
            "actor_id": actor_id,
        },
    )


def device_inventory_item_allocated(
    *,
    inventory_item_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None,
) -> DomainEvent:
    """ADR-0018 §1: the allocated-to organization lands here, on the event's `org_id`/payload —
    never as a persisted column on `device_inventory` itself; the durable, queryable link is
    `Device.inventory_id` on the row `allocate_device_inventory_item` creates immediately
    after, in the same transaction."""
    return _new_event(
        event_type="DeviceInventoryItemAllocated",
        aggregate_type="DeviceInventoryItem",
        aggregate_id=inventory_item_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"organization_id": organization_id, "actor_id": actor_id},
    )
