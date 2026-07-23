import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `fleet_device.domain.value_objects.DeviceLifecycleState` (Database Design §5.2's
 * `lifecycle_state ENUM(registered,activated,assigned,suspended,retired)`). `entities.Device`'s
 * own docstring gives the exact edges this frontend's action buttons must follow:
 * `registered --activate()--> activated <--suspend()/reactivate()--> suspended`,
 * `activated --assign--> assigned --unassign--> activated`,
 * `assigned | activated --retire()--> retired` (terminal). */
export type DeviceLifecycleState = "registered" | "activated" | "assigned" | "suspended" | "retired";

/** `fleet_device.domain.value_objects.CameraPosition` (Database Design §5.3's
 * `position ENUM(in_cabin,road_facing,other)`). Read-only here — see this module's own note on
 * why no camera-management UI is built (`DevicesPage.tsx`'s docstring). */
export type CameraPosition = "in_cabin" | "road_facing" | "other";

export interface Camera {
  id: string;
  channelNo: number;
  position: CameraPosition;
  label: string | null;
}

export interface Device {
  id: string;
  organizationId: string;
  terminalId: string;
  model: string | null;
  vendor: string | null;
  simMsisdn: string | null;
  lifecycleState: DeviceLifecycleState;
  lastSeenAt: string | null;
  createdAt: string;
  updatedAt: string;
  cameras: Camera[];
}

interface CameraWire {
  id: string;
  channel_no: number;
  position: string;
  label: string | null;
}

/** Wire shape of `fleet_device.api.schemas.DeviceResponse` — snake_case, exactly as the backend
 * serializes it (`backend/raad/modules/fleet_device/api/schemas.py`). Carries no `vehicle_id`/
 * assignment field at all — see `listVehiclesForPicker`/`assignDeviceToVehicle`'s own docstrings
 * for what that means for this frontend's assignment display. */
interface DeviceWire {
  id: string;
  organization_id: string;
  terminal_id: string;
  model: string | null;
  vendor: string | null;
  sim_msisdn: string | null;
  lifecycle_state: string;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
  cameras: CameraWire[];
}

function toDevice(wire: DeviceWire): Device {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    terminalId: wire.terminal_id,
    model: wire.model,
    vendor: wire.vendor,
    simMsisdn: wire.sim_msisdn,
    lifecycleState: wire.lifecycle_state as DeviceLifecycleState,
    lastSeenAt: wire.last_seen_at,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    cameras: wire.cameras.map((camera) => ({
      id: camera.id,
      channelNo: camera.channel_no,
      position: camera.position as CameraPosition,
      label: camera.label,
    })),
  };
}

/** `GET /devices` (API Contracts §4.2) — paginated/filterable/sortable via `usePaginatedQuery`.
 * Whitelist confirmed against `modules/fleet_device/infra/repositories.py`'s
 * `SqlAlchemyDeviceRepository`: filterable `organization_id`/`lifecycle_state`, sortable
 * `terminal_id`/`lifecycle_state`/`created_at`/`updated_at`, searchable
 * `terminal_id`/`model`/`vendor`. `sim_msisdn` is never filterable/sortable/searchable (PII,
 * masked in logs per that repository's own comment) — this frontend does not offer it as a
 * filter either. Not yet scope-filtered server-side (the same system-wide, already-flagged gap
 * every list endpoint in this codebase carries). */
export async function listDevices(params: OffsetListParams): Promise<OffsetPage<Device>> {
  const wire = await apiRequest<OffsetPageWire<DeviceWire>>(`/devices?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toDevice);
}

export async function getDevice(id: string): Promise<Device> {
  const wire = await apiRequest<DeviceWire>(`/devices/${id}`);
  return toDevice(wire);
}

export interface RegisterDeviceInput {
  organizationId: string;
  terminalId: string;
  model?: string | null;
  vendor?: string | null;
  simMsisdn?: string | null;
}

/** `POST /devices` (`RegisterDeviceRequest`) exactly: `organization_id`, `terminal_id`, `model`,
 * `vendor`, `sim_msisdn`. Per the seeded RBAC matrix, `founder`/`org_admin`/`support_staff` all
 * hold `fleet_device.devices.create` (a wider set than `vehicles.create`, which excludes
 * `support_staff`) — `DevicesPage`'s own `canManageLifecycle` flag mirrors this. */
export async function registerDevice(input: RegisterDeviceInput): Promise<Device> {
  const wire = await apiRequest<DeviceWire>("/devices", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      terminal_id: input.terminalId,
      model: input.model ?? null,
      vendor: input.vendor ?? null,
      sim_msisdn: input.simMsisdn ?? null,
    },
  });
  return toDevice(wire);
}

/** `POST /devices/{id}/activate` (API Contracts §4.2 verbatim) — the *only* route for the
 * Registered→Activated edge (`entities.Device.activate`). Kept as its own function, distinct
 * from `updateDeviceLifecycle`'s PATCH-based `"activated"` target below (which is the *separate*
 * Suspended→Activated/"reactivate" edge) — two different backend routes for two different
 * documented state-machine edges, never conflated. */
export async function activateDevice(id: string): Promise<Device> {
  const wire = await apiRequest<DeviceWire>(`/devices/${id}/activate`, { method: "POST" });
  return toDevice(wire);
}

/** `PATCH /devices/{id}` (`UpdateDeviceRequest`) — `lifecycle_state` ∈ `"activated"` (reactivate,
 * Suspended→Activated), `"suspended"`, `"retired"`. Registered→Activated has its own route
 * (`activateDevice` above); `"assigned"`/`"registered"` are never valid PATCH targets
 * (`routers.py`'s `update_device` rejects anything else with a `ValidationError`). */
export async function updateDeviceLifecycle(
  id: string,
  lifecycleState: "activated" | "suspended" | "retired",
): Promise<Device> {
  const wire = await apiRequest<DeviceWire>(`/devices/${id}`, {
    method: "PATCH",
    body: { lifecycle_state: lifecycleState },
  });
  return toDevice(wire);
}

export interface DeviceAssignment {
  id: string;
  organizationId: string;
  deviceId: string;
  vehicleId: string;
  assignedBy: string | null;
  assignedAt: string;
  unassignedAt: string | null;
  isActive: boolean;
}

interface DeviceAssignmentWire {
  id: string;
  organization_id: string;
  device_id: string;
  vehicle_id: string;
  assigned_by: string | null;
  assigned_at: string;
  unassigned_at: string | null;
  is_active: boolean;
}

function toDeviceAssignment(wire: DeviceAssignmentWire): DeviceAssignment {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    deviceId: wire.device_id,
    vehicleId: wire.vehicle_id,
    assignedBy: wire.assigned_by,
    assignedAt: wire.assigned_at,
    unassignedAt: wire.unassigned_at,
    isActive: wire.is_active,
  };
}

/** `POST /devices/{id}/assign` (body `{vehicle_id}`, API Contracts §4.2 verbatim) — the distinct,
 * explicit "assign device to vehicle" action (`AssignDeviceForm.tsx`), never folded into a plain
 * form field, matching the backend's own explicit-command modeling
 * (`fleet_device.application.commands.AssignDeviceToVehicleCommand`).
 *
 * **Real backend behavior to design around:** `assign_device_to_vehicle`
 * (`application/services.py`) enforces "one active binding per device" *and* "one active device
 * per vehicle" (Phase 2 §19) via `ensure_device_has_no_active_assignment`/
 * `ensure_vehicle_has_no_active_device` — attempting either while one is already active raises a
 * `ConflictError` (`core.errors.exceptions`, HTTP 409, `error.code === "CONFLICT"`) with a message
 * naming the vehicle/device already involved. This module surfaces that message verbatim via a
 * toast (`AssignDeviceForm.tsx`'s `onError`) rather than a generic "something went wrong" — this
 * is a safety-adjacent invariant (`docs/architecture/frontend-flutter-master-roadmap.md`'s own
 * Phase F3 entry), so silently swallowing or misreporting it would hide a genuine double-binding
 * attempt from the operator.
 */
export async function assignDeviceToVehicle(deviceId: string, vehicleId: string): Promise<DeviceAssignment> {
  const wire = await apiRequest<DeviceAssignmentWire>(`/devices/${deviceId}/assign`, {
    method: "POST",
    body: { vehicle_id: vehicleId },
  });
  return toDeviceAssignment(wire);
}

/** `POST /devices/{id}/reassign` (body `{vehicle_id}`, API Contracts §4.2 verbatim) — closes the
 * device's current active assignment and opens a new one to `vehicleId` in one request
 * (`reassign_device`, `application/services.py`; emits `DeviceReassigned`). Still subject to the
 * "one active device per vehicle" guard against the *new* target vehicle — see
 * `assignDeviceToVehicle`'s docstring for the identical conflict-surfacing treatment. */
export async function reassignDevice(deviceId: string, vehicleId: string): Promise<DeviceAssignment> {
  const wire = await apiRequest<DeviceAssignmentWire>(`/devices/${deviceId}/reassign`, {
    method: "POST",
    body: { vehicle_id: vehicleId },
  });
  return toDeviceAssignment(wire);
}

/** `POST /devices/{id}/unassign` (API Contracts §4.2 verbatim, no body) — closes the device's
 * active assignment; the device's `lifecycle_state` returns to `"activated"`
 * (`entities.Device.mark_unassigned`). */
export async function unassignDevice(deviceId: string): Promise<DeviceAssignment> {
  const wire = await apiRequest<DeviceAssignmentWire>(`/devices/${deviceId}/unassign`, { method: "POST" });
  return toDeviceAssignment(wire);
}

export interface OrganizationOption {
  id: string;
  name: string;
}

interface OrganizationOptionWire {
  id: string;
  name: string;
}

/** Minimal, read-only `GET /organizations` lookup — see `features/fleet-devices/vehicles/api.ts`'s
 * identical function for why this is deliberately its own self-contained copy rather than a
 * shared/cross-imported helper. */
export async function listOrganizationsForPicker(search: string): Promise<OrganizationOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "name", direction: "asc" },
    filters: { status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<OrganizationOptionWire>>(`/organizations?${query}`);
  return wire.data.map((org) => ({ id: org.id, name: org.name }));
}

export interface VehicleOption {
  id: string;
  plateNo: string;
  label: string | null;
}

interface VehicleOptionWire {
  id: string;
  plate_no: string;
  label: string | null;
}

/** Minimal, read-only `GET /vehicles` lookup backing `AssignDeviceForm`'s vehicle picker.
 * Deliberately its own self-contained read rather than an import from
 * `features/fleet-devices/vehicles/api.ts` — the same "own minimal read, don't reach into a
 * sibling feature folder" discipline `listOrganizationsForPicker` above already follows, applied
 * one level deeper since `vehicles/` and `devices/` are kept as independently self-contained
 * entity folders (see that module's own note).
 *
 * Filtered to `organizationId` and `status=active` as a **UX convenience only** — the backend
 * itself does *not* enforce that an assigned vehicle belongs to the same organization as the
 * device (`assign_device_to_vehicle`'s only vehicle pre-condition is `ensure_vehicle_exists`, no
 * org-match check at all — a real gap flagged in this phase's report, not silently
 * papered over here). Restricting the picker this way guides an operator toward the sane choice
 * without pretending the backend enforces it. */
export async function listVehiclesForPicker(organizationId: string, search: string): Promise<VehicleOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "plate_no", direction: "asc" },
    filters: { organization_id: organizationId, status: "active" },
    search,
  });
  const wire = await apiRequest<OffsetPageWire<VehicleOptionWire>>(`/vehicles?${query}`);
  return wire.data.map((vehicle) => ({ id: vehicle.id, plateNo: vehicle.plate_no, label: vehicle.label }));
}
