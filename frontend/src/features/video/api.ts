import { apiRequest } from "../../shared/api/client";
import { buildOffsetListQuery } from "../../shared/api/listParams";
import type { OffsetPageWire } from "../../shared/api/types";

/** `fleet_device.domain.value_objects.CameraPosition` (Database Design §5.3's
 * `position ENUM(in_cabin,road_facing,other)`) — mirrors `features/fleet-devices/devices/api.ts`'s
 * own identical type (this module keeps its own minimal copy rather than cross-importing from a
 * sibling feature folder, the same "own minimal, self-contained read" discipline that module's own
 * `listVehiclesForPicker` docstring documents). */
export type CameraPosition = "in_cabin" | "road_facing" | "other";

export interface VideoCameraOption {
  id: string;
  channelNo: number;
  position: CameraPosition;
  label: string | null;
}

/** `fleet_device.domain.value_objects.DeviceLifecycleState` — surfaced only as an informational
 * badge in the picker (below), never used to block a selection client-side: the backend's own
 * `POST /video/live` is the real authority on whether a device/camera can stream. */
export type DeviceLifecycleState = "registered" | "activated" | "assigned" | "suspended" | "retired";

/**
 * A device eligible for the F10 picker (`VideoPage.tsx`).
 *
 * **No `vehicleId` — this is a real, confirmed contract gap, not an oversight.**
 * `fleet_device.api.schemas.DeviceResponse` carries no `vehicle_id` field, and there is no
 * `GET` route anywhere that resolves "which device is assigned to vehicle X" (only the write-side
 * `POST /devices/{id}/assign`/`/reassign`/`/unassign` return a `DeviceAssignmentResponse`, never
 * queryable afterward) — `features/fleet-devices/devices/api.ts`'s own `DeviceWire` docstring
 * already documents this exact gap for the assignment UI. `POST /video/live`/`/playback` take
 * `device_id`/`camera_id` directly, never `vehicle_id`, so this picker is device-first, not
 * vehicle-first — see `VideoPage.tsx`'s own module docstring for the full reasoning.
 */
export interface VideoDeviceOption {
  id: string;
  terminalId: string;
  model: string | null;
  vendor: string | null;
  lifecycleState: DeviceLifecycleState;
  cameras: VideoCameraOption[];
}

interface CameraWire {
  id: string;
  channel_no: number;
  position: string;
  label: string | null;
}

/** Wire shape of `fleet_device.api.schemas.DeviceResponse` — only the fields this picker actually
 * uses are declared (the real response carries more, e.g. `sim_msisdn`/`imei`/`iccid` — irrelevant
 * here and never read). */
interface DeviceWire {
  id: string;
  terminal_id: string;
  model: string | null;
  vendor: string | null;
  lifecycle_state: string;
  cameras: CameraWire[];
}

function toVideoDeviceOption(wire: DeviceWire): VideoDeviceOption {
  return {
    id: wire.id,
    terminalId: wire.terminal_id,
    model: wire.model,
    vendor: wire.vendor,
    lifecycleState: wire.lifecycle_state as DeviceLifecycleState,
    cameras: wire.cameras.map((camera) => ({
      id: camera.id,
      channelNo: camera.channel_no,
      position: camera.position as CameraPosition,
      label: camera.label,
    })),
  };
}

/**
 * `GET /devices` — tenant-scoped server-side since ADR-0021 (`SqlAlchemyDeviceRepository.
 * list_page`/`list_all` apply `_apply_scope`, confirmed directly against that repository's own
 * source; `fleet_device/api/routers.py`'s own module docstring claiming "neither list route is
 * itself scope-filtered yet" predates that fix and is stale — flagged here, not silently trusted).
 * `org_admin` holds exactly the one narrow `fleet_device.devices.read` grant ADR-0018 introduced
 * (CLAUDE.md's Fleet Device section) — this is the *only* other place in the Organization
 * dashboard this permission is exercised beyond `VehiclesPage`'s own `last_seen_at`-only
 * "Tracking" drawer; flagged as a real, deliberate widening of "device-derived data an Org Admin
 * session can reach," not a new permission grant.
 *
 * Client-side filtered to devices carrying at least one camera — a device with zero cameras has
 * nothing this feature can ever request, the same "hide what the feature genuinely cannot use"
 * reasoning as `listVehiclesForPicker`'s own `status=active` filter (a UX convenience, not a
 * second authorization layer). No `organization_id` filter is sent — scope is already enforced
 * server-side, so a client-supplied one would be redundant.
 */
export async function listDevicesForVideoPicker(search: string): Promise<VideoDeviceOption[]> {
  const query = buildOffsetListQuery({
    page: 1,
    pageSize: 100,
    sort: { field: "terminal_id", direction: "asc" },
    filters: {},
    search,
  });
  const wire = await apiRequest<OffsetPageWire<DeviceWire>>(`/devices?${query}`);
  return wire.data.map(toVideoDeviceOption).filter((device) => device.cameras.length > 0);
}

export type VideoSessionPurpose = "live" | "playback" | "intercom";
export type VideoSessionStatus = "requested" | "active" | "ended" | "failed";

export interface VideoSession {
  id: string;
  organizationId: string;
  deviceId: string;
  cameraId: string;
  purpose: VideoSessionPurpose;
  requestedBy: string;
  windowStart: string | null;
  windowEnd: string | null;
  status: VideoSessionStatus;
  startedAt: string | null;
  endedAt: string | null;
  createdAt: string;
  /** `ws://.../viewer?token=...` — the JT1078 relay's own viewer endpoint, a raw WebSocket
   * carrying hand-rolled binary FLV bytes (`services/jt1078/src/viewer/`), never proxied through
   * this backend. See `VideoPage.tsx`'s own module docstring for why this frontend cannot decode/
   * render it into a `<video>` element yet. `null` only if no `VideoProviderPort` is bound on this
   * deployment (`video/api/routers.py`'s own module docstring). */
  streamUrl: string | null;
  /** ADR-0036 — populated only on an intercom session's own response (`POST /video/intercom`);
   * `null`/absent for every other purpose/route (optional so every pre-existing test fixture
   * across this feature stays valid unchanged). A second, independently-tokened WebSocket URL
   * (the same relay, a different token) for sending the operator's own mic audio toward the
   * device — see `useIntercomController.ts`. */
  uplinkUrl?: string | null;
}

interface VideoSessionWire {
  id: string;
  organization_id: string;
  device_id: string;
  camera_id: string;
  purpose: string;
  requested_by: string;
  window_start: string | null;
  window_end: string | null;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  stream_url: string | null;
  uplink_url: string | null;
}

function toVideoSession(wire: VideoSessionWire): VideoSession {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    deviceId: wire.device_id,
    cameraId: wire.camera_id,
    purpose: wire.purpose as VideoSessionPurpose,
    requestedBy: wire.requested_by,
    windowStart: wire.window_start,
    windowEnd: wire.window_end,
    status: wire.status as VideoSessionStatus,
    startedAt: wire.started_at,
    endedAt: wire.ended_at,
    createdAt: wire.created_at,
    streamUrl: wire.stream_url,
    uplinkUrl: wire.uplink_url ?? null,
  };
}

/** A session in either of these two statuses is still "open" on the backend — needs an explicit
 * `stopVideoSession` call before it's really torn down. Mirrors `VideoApplicationService`'s own
 * `_OPEN_STATUSES` (`backend/raad/modules/video/application/services.py`) exactly. */
export const OPEN_VIDEO_SESSION_STATUSES: ReadonlySet<VideoSessionStatus> = new Set([
  "requested",
  "active",
]);

/** `POST /video/live` (API Contracts §4.5) — body `{device_id, camera_id}` verbatim, no other
 * field exists on `RequestLiveVideoRequest`. D5-enforced entirely server-side before any session
 * is created; this call raises `ApiError` (403 `VIDEO_FORBIDDEN`, 404, or 500 if no
 * `VideoProviderPort` is bound on this deployment) exactly like every other mutation in this
 * frontend — `VideoPage.tsx` maps those to its own error/unavailable states, never a client-side
 * guess at authorization. */
export async function requestLiveVideo(deviceId: string, cameraId: string): Promise<VideoSession> {
  const wire = await apiRequest<VideoSessionWire>("/video/live", {
    method: "POST",
    body: { device_id: deviceId, camera_id: cameraId },
  });
  return toVideoSession(wire);
}

/** `POST /video/intercom` (ADR-0036) — same body shape as `requestLiveVideo`. Org Admin
 * (+ permitted RAAD staff) only, never Parent (RBAC-excluded, not just D5-gated — see that ADR
 * §3); raises `ApiError` (403, 404, 409 if the device already has an open intercom session, or
 * 500 if no `VideoProviderPort` is bound) exactly like `requestLiveVideo`. */
export async function requestIntercom(deviceId: string, cameraId: string): Promise<VideoSession> {
  const wire = await apiRequest<VideoSessionWire>("/video/intercom", {
    method: "POST",
    body: { device_id: deviceId, camera_id: cameraId },
  });
  return toVideoSession(wire);
}

/** `POST /video/sessions/{id}/stop` (API Contracts §4.5) — idempotent on the backend (a session
 * already `ended`/`failed` short-circuits before any provider call, `VideoApplicationService.
 * stop_video_session`'s own docstring), so this frontend does not need to guard against calling it
 * twice (unmount racing an explicit Stop click, for instance). */
export async function stopVideoSession(
  sessionId: string,
  options?: { keepalive?: boolean },
): Promise<VideoSession> {
  const wire = await apiRequest<VideoSessionWire>(`/video/sessions/${sessionId}/stop`, {
    method: "POST",
    keepalive: options?.keepalive,
  });
  return toVideoSession(wire);
}
