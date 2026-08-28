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

from dataclasses import dataclass, field
from datetime import datetime

from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.modules.fleet_device.domain.entities import (
    Camera,
    Device,
    DeviceAssignment,
    DeviceInventoryItem,
    Vehicle,
)


@dataclass(frozen=True)
class GetVehicleByIdQuery:
    vehicle_id: str


@dataclass(frozen=True)
class ListVehiclesQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class GetDeviceByIdQuery:
    device_id: str


@dataclass(frozen=True)
class ListDevicesQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class TrackingStatusDTO:
    """The only device-derived fact an Org Admin session may ever receive (Device Domain
    Overhaul architecture review) — no `device_id`, `terminal_id`, or any other hardware
    identifier, by construction. Populated only on `GetVehicleByIdQuery` (see
    `VehicleApplicationService.get_vehicle_by_id`'s own docstring for why the paginated list
    path deliberately leaves this `None` instead).

    **Deliberately carries `last_seen_at` only, no derived `is_connected` boolean.** A device
    that reported once and then went silent for a week would make "last_seen_at IS NOT NULL"
    a false "connected" signal — and the only source that could answer "is it online *right
    now*" honestly is the JT808 service's own Redis session state (Phase 3.4 §5), which this
    query never reads. Presenting a fabricated real-time status badge from a historical DB
    column would violate this codebase's own "fail loudly, don't fake it" posture; the frontend
    renders "not yet connected" / "last seen <relative time>" from this raw timestamp instead."""

    last_seen_at: datetime | None


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
    tracking_status: TrackingStatusDTO | None = None


@dataclass(frozen=True)
class VehicleStatsDTO:
    """ADR-0020: "Total Vehicles" KPI."""

    total: int


@dataclass(frozen=True)
class DeviceStatsDTO:
    """ADR-0020 §3: "Total/Online/Offline Devices" KPI. `offline` is derived
    (`total - online`), not a third query — see `DeviceRepository.count_online`'s own
    docstring."""

    total: int
    online: int
    offline: int


@dataclass(frozen=True)
class OnlineDeviceAssignmentDTO:
    """ADR-0031 (Fleet Overview read model) — the application-layer mirror of
    `domain.repositories.OnlineDeviceAssignment`, returned by `DeviceApplicationService.
    list_online_devices_with_vehicle_assignment`. `tracking`'s new `FleetOverviewApplicationService`
    is the sole consumer."""

    device_id: str
    terminal_id: str
    vehicle_id: str


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
    imei: str | None
    iccid: str | None
    serial_number: str | None
    lifecycle_state: str
    last_seen_at: datetime | None
    #: ADR-0027 Change 2: mirrors `Device.is_online` (ADR-0020) directly — read, never derived
    #: or duplicated. Previously persisted but only ever read in aggregate
    #: (`DeviceRepository.count_online()`), never surfaced per device.
    is_online: bool
    created_at: datetime
    updated_at: datetime
    cameras: tuple[CameraDTO, ...]
    inventory_id: str | None = None
    #: The device's own real `0x1003`-reported `input_audio_codec` (`AudioCapability.codec`,
    #: ADR-0033), raw and undecoded. Exposed starting with the G.711A audio fix - a real consumer
    #: now exists (`video/api/routers.py` threading it into `VideoProviderPort.start_live`), the
    #: same "not exposed until a real consumer needs it" reversal `is_online` (ADR-0027) already
    #: established a precedent for. `None` when no `AudioCapability` has been captured yet.
    audio_codec: int | None = None


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
        imei=str(device.imei) if device.imei is not None else None,
        iccid=str(device.iccid) if device.iccid is not None else None,
        serial_number=(
            str(device.serial_number) if device.serial_number is not None else None
        ),
        lifecycle_state=device.lifecycle_state.value,
        last_seen_at=device.last_seen_at,
        is_online=device.is_online,
        created_at=device.created_at,
        updated_at=device.updated_at,
        cameras=tuple(camera_to_dto(camera) for camera in device.cameras),
        inventory_id=str(device.inventory_id) if device.inventory_id is not None else None,
        audio_codec=(
            device.audio_capability.codec if device.audio_capability is not None else None
        ),
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


@dataclass(frozen=True)
class DeviceInventoryItemDTO:
    id: str
    serial_number: str
    imei: str | None
    iccid: str | None
    model: str | None
    vendor: str | None
    state: str
    created_at: datetime
    updated_at: datetime


def inventory_item_to_dto(item: DeviceInventoryItem) -> DeviceInventoryItemDTO:
    """Shared mapper — the only place a `DeviceInventoryItem` aggregate is projected into its
    DTO."""
    return DeviceInventoryItemDTO(
        id=str(item.id),
        serial_number=str(item.serial_number),
        imei=str(item.imei) if item.imei is not None else None,
        iccid=str(item.iccid) if item.iccid is not None else None,
        model=item.model,
        vendor=item.vendor,
        state=item.state.value,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
