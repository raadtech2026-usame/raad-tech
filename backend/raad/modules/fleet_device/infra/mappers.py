"""ORM ↔ Domain mappers for `fleet_device` (Backend LLD §7.1 "aggregate-in/aggregate-out";
§17 `db`). Mappers own **every** conversion between SQLAlchemy rows and domain objects —
repositories (`repositories.py`) never construct or read ORM columns directly outside calling
these functions, and never return an ORM model to a caller. Mirrors
`iam`/`organization.infra.mappers`'s `existing=` in-place-update pattern exactly.

The `Device` aggregate owns `Camera` children (Phase 7.1), so `device_to_model` also syncs
the camera collection: existing camera rows are matched by id and updated in place (keeping
the session tracking the rows it already knows), new cameras are appended as new
`CameraModel` rows (the relationship's cascade persists them). The domain has no
camera-removal behavior, so no row is ever deleted here — if that behavior is ever
documented, this sync must learn deletion alongside it.

`DeviceAssignmentModel`'s one-active-binding invariant is enforced entirely by its two partial
unique indexes (Database Design §5.4, ADR-0002) — there is no denormalized key column for this
mapper to avoid touching; `unassigned_at` is the only column mediating "active" and it maps
normally like any other field."""

from __future__ import annotations

from datetime import datetime

from raad.modules.fleet_device.domain.entities import (
    Camera,
    Device,
    DeviceAssignment,
    Vehicle,
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
from raad.modules.fleet_device.infra.models import (
    CameraModel,
    DeviceAssignmentModel,
    DeviceModel,
    VehicleModel,
)


def _naive(value: datetime | None) -> datetime | None:
    """Strips tzinfo before a domain-computed timestamp crosses into a `DateTime(timezone=
    False)` column (ADR-0002) — the same pattern `core.events.outbox.OutboxWriter.write()`
    already applies to `DomainEvent.occurred_at`. `DeviceAssignment.assigned_at`/
    `unassigned_at` are set from `Clock.now()` (tz-aware, `SystemClock`) directly, unlike the
    audit-mixin `created_at`/`updated_at` columns, which already get a naive value from
    `core.db.mixins.utcnow`'s own Python-level `default=`."""
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


# --- Vehicle ------------------------------------------------------------------------------


def vehicle_to_model(
    vehicle: Vehicle, *, existing: VehicleModel | None = None
) -> VehicleModel:
    """Projects a `Vehicle` aggregate onto its ORM row. If `existing` is given, mutates and
    returns that same instance (so the SQLAlchemy session keeps tracking the one row it
    already knows about, rather than a duplicate) — otherwise constructs a new
    `VehicleModel`."""
    model = existing if existing is not None else VehicleModel(id=str(vehicle.id))
    model.organization_id = str(vehicle.organization_id)
    model.plate_no = vehicle.plate_no
    model.label = vehicle.label
    model.capacity = vehicle.capacity
    model.status = vehicle.status.value
    model.created_at = _naive(vehicle.created_at)
    model.updated_at = _naive(vehicle.updated_at)
    return model


def model_to_vehicle(model: VehicleModel) -> Vehicle:
    return Vehicle(
        id=VehicleId(model.id),
        organization_id=OrganizationId(model.organization_id),
        plate_no=model.plate_no,
        label=model.label,
        capacity=model.capacity,
        status=VehicleStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# --- Device (+ Camera children) -----------------------------------------------------------


def camera_to_model(
    camera: Camera,
    *,
    device_id: str,
    organization_id: str,
    existing: CameraModel | None = None,
) -> CameraModel:
    model = existing if existing is not None else CameraModel(id=str(camera.id))
    model.organization_id = organization_id
    model.device_id = device_id
    model.channel_no = camera.channel_no
    model.label = camera.label
    model.position = camera.position.value
    return model


def model_to_camera(model: CameraModel) -> Camera:
    return Camera(
        id=CameraId(model.id),
        channel_no=model.channel_no,
        position=CameraPosition(model.position),
        label=model.label,
    )


def device_to_model(
    device: Device, *, existing: DeviceModel | None = None
) -> DeviceModel:
    """Projects a `Device` aggregate (including its cameras) onto its ORM row — see the
    module docstring for the camera-collection sync rules."""
    model = existing if existing is not None else DeviceModel(id=str(device.id))
    model.organization_id = str(device.organization_id)
    model.terminal_id = str(device.terminal_id)
    model.model = device.model
    model.vendor = device.vendor
    model.sim_msisdn = str(device.sim_msisdn) if device.sim_msisdn is not None else None
    model.lifecycle_state = device.lifecycle_state.value
    model.auth_key_hash = device.auth_key_hash
    model.last_seen_at = device.last_seen_at
    model.created_at = _naive(device.created_at)
    model.updated_at = _naive(device.updated_at)

    existing_rows = {row.id: row for row in model.cameras}
    for camera in device.cameras:
        row = existing_rows.get(str(camera.id))
        if row is not None:
            camera_to_model(
                camera,
                device_id=str(device.id),
                organization_id=str(device.organization_id),
                existing=row,
            )
        else:
            model.cameras.append(
                camera_to_model(
                    camera,
                    device_id=str(device.id),
                    organization_id=str(device.organization_id),
                )
            )
    return model


def model_to_device(model: DeviceModel) -> Device:
    return Device(
        id=DeviceId(model.id),
        organization_id=OrganizationId(model.organization_id),
        terminal_id=TerminalId(model.terminal_id),
        model=model.model,
        vendor=model.vendor,
        sim_msisdn=Msisdn(model.sim_msisdn) if model.sim_msisdn is not None else None,
        lifecycle_state=DeviceLifecycleState(model.lifecycle_state),
        auth_key_hash=model.auth_key_hash,
        last_seen_at=model.last_seen_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
        cameras=[model_to_camera(row) for row in model.cameras],
    )


# --- DeviceAssignment ---------------------------------------------------------------------


def assignment_to_model(
    assignment: DeviceAssignment, *, existing: DeviceAssignmentModel | None = None
) -> DeviceAssignmentModel:
    model = (
        existing
        if existing is not None
        else DeviceAssignmentModel(id=str(assignment.id))
    )
    model.organization_id = str(assignment.organization_id)
    model.device_id = str(assignment.device_id)
    model.vehicle_id = str(assignment.vehicle_id)
    model.assigned_by = assignment.assigned_by
    model.assigned_at = _naive(assignment.assigned_at)
    model.unassigned_at = _naive(assignment.unassigned_at)
    return model


def model_to_assignment(model: DeviceAssignmentModel) -> DeviceAssignment:
    return DeviceAssignment(
        id=AssignmentId(model.id),
        organization_id=OrganizationId(model.organization_id),
        device_id=DeviceId(model.device_id),
        vehicle_id=VehicleId(model.vehicle_id),
        assigned_by=model.assigned_by,
        assigned_at=model.assigned_at,
        unassigned_at=model.unassigned_at,
    )
