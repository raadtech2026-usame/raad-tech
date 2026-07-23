import { apiRequest } from "../../../shared/api/client";
import { buildOffsetListQuery, type OffsetListParams } from "../../../shared/api/listParams";
import { toOffsetPage, type OffsetPage, type OffsetPageWire } from "../../../shared/api/types";

/** `fleet_device.domain.value_objects.VehicleStatus` (Database Design §5.1's
 * `status ENUM(active,inactive,maintenance)`). No documented state machine governs these three
 * values (`domain/entities.py`'s `Vehicle` docstring: "treated as directly settable states with
 * idempotent same-state no-ops, not an invented transition graph") — every status is reachable
 * from every other, exactly like `organization.Organization.status`. */
export type VehicleStatus = "active" | "inactive" | "maintenance";

/** The only device-derived data this frontend ever receives for a Vehicle (Device Domain
 * Overhaul architecture review) — no `deviceId`/`terminalId`/hardware identifier of any kind,
 * by construction (`fleet_device.application.queries.TrackingStatusDTO`'s own docstring).
 * Deliberately `lastSeenAt` only, no derived "connected" boolean — see that same docstring for
 * why: the only source that could answer "online right now" honestly is the JT808 service's
 * Redis session state, which this field never reads. */
export interface TrackingStatus {
  lastSeenAt: string | null;
}

export interface Vehicle {
  id: string;
  organizationId: string;
  plateNo: string;
  label: string | null;
  capacity: number | null;
  status: VehicleStatus;
  createdAt: string;
  updatedAt: string;
  /** `null` on `listVehicles` (the list endpoint never populates this — avoids an N+1 device
   * lookup per page row) and whenever no active device is assigned; populated only by
   * `getVehicle` (`GET /vehicles/{id}`). */
  trackingStatus: TrackingStatus | null;
}

interface TrackingStatusWire {
  last_seen_at: string | null;
}

/** Wire shape of `fleet_device.api.schemas.VehicleResponse` — snake_case, exactly as the backend
 * serializes it (`backend/raad/modules/fleet_device/api/schemas.py`). */
interface VehicleWire {
  id: string;
  organization_id: string;
  plate_no: string;
  label: string | null;
  capacity: number | null;
  status: string;
  created_at: string;
  updated_at: string;
  tracking_status: TrackingStatusWire | null;
}

function toVehicle(wire: VehicleWire): Vehicle {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    plateNo: wire.plate_no,
    label: wire.label,
    capacity: wire.capacity,
    status: wire.status as VehicleStatus,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    trackingStatus: wire.tracking_status ? { lastSeenAt: wire.tracking_status.last_seen_at } : null,
  };
}

/** `GET /vehicles` (API Contracts §4.2) — paginated/filterable/sortable via `usePaginatedQuery`.
 * Whitelist confirmed against `modules/fleet_device/infra/repositories.py`'s
 * `SqlAlchemyVehicleRepository`: filterable `organization_id`/`status`, sortable
 * `plate_no`/`status`/`created_at`/`updated_at`, searchable `plate_no`/`label`. Not yet
 * scope-filtered server-side (CLAUDE.md's own flagged, system-wide gap — every `list_page` still
 * applies an unrestricted `TenantRegionScope`), matching every other list endpoint in this
 * codebase: every viewer who can reach this route currently sees every vehicle, not just their
 * own organization's. */
export async function listVehicles(params: OffsetListParams): Promise<OffsetPage<Vehicle>> {
  const wire = await apiRequest<OffsetPageWire<VehicleWire>>(`/vehicles?${buildOffsetListQuery(params)}`);
  return toOffsetPage(wire, toVehicle);
}

export async function getVehicle(id: string): Promise<Vehicle> {
  const wire = await apiRequest<VehicleWire>(`/vehicles/${id}`);
  return toVehicle(wire);
}

export interface RegisterVehicleInput {
  organizationId: string;
  plateNo: string;
  label?: string | null;
  capacity?: number | null;
}

/** `POST /vehicles` (`RegisterVehicleRequest`, `fleet_device.api.schemas`) exactly:
 * `organization_id`, `plate_no`, `label`, `capacity`. Per RBAC (`migrations/versions/
 * 20260721_..._iam_create_role_permissions_table.py`), only `founder`/`org_admin` hold
 * `fleet_device.vehicles.create` — `VehiclesPage`'s own `canManage` flag mirrors this as a
 * presentation hint only (`.claude/rules/frontend.md` #2). */
export async function registerVehicle(input: RegisterVehicleInput): Promise<Vehicle> {
  const wire = await apiRequest<VehicleWire>("/vehicles", {
    method: "POST",
    body: {
      organization_id: input.organizationId,
      plate_no: input.plateNo,
      label: input.label ?? null,
      capacity: input.capacity ?? null,
    },
  });
  return toVehicle(wire);
}

/** `PATCH /vehicles/{id}` (`UpdateVehicleRequest`) — the only field the Application layer
 * exposes is `status`, mapped server-side to `activate_vehicle`/`deactivate_vehicle`/
 * `mark_vehicle_under_maintenance` (`routers.py`'s `update_vehicle`). Unlike `iam`'s
 * `UserStatus`, every one of the three `VehicleStatus` values is a valid PATCH target — there is
 * no restricted subset (see this module's own `VehicleStatus` docstring). */
export async function updateVehicleStatus(id: string, status: VehicleStatus): Promise<Vehicle> {
  const wire = await apiRequest<VehicleWire>(`/vehicles/${id}`, {
    method: "PATCH",
    body: { status },
  });
  return toVehicle(wire);
}

export interface OrganizationOption {
  id: string;
  name: string;
}

interface OrganizationOptionWire {
  id: string;
  name: string;
}

/** Minimal, read-only `GET /organizations` lookup backing the register-vehicle form's
 * organization picker (shown only when the signed-in principal has no `organizationId` of their
 * own — i.e. every role except `org_admin`) and the list/detail views' organization-name display.
 * Deliberately self-contained rather than importing `features/organizations/api.ts` or
 * `features/fleet-devices/devices/api.ts`'s identical copy: `.claude/rules/frontend.md` #1 mirrors
 * backend bounded contexts onto feature folders, and no cross-feature-folder `api.ts` import
 * exists anywhere in this codebase yet (`admin/users/api.ts`'s `listOrganizationsForPicker`
 * docstring establishes the same "own minimal read" precedent this module follows) — `vehicles/`
 * and `devices/` are kept as independently self-contained entity folders under `fleet-devices/`
 * for the same reason, even though both ultimately belong to the same `fleet_device` bounded
 * context. */
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
