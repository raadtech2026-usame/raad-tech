import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Cpu, Video, WifiOff } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { useAuthStore } from "../../shared/stores/authStore";
import type { Role } from "../../shared/api/types";
import { MultiCameraVideoPanel } from "../video/MultiCameraVideoPanel";
import { listVehiclesForTracking } from "./api";
import { useActiveTripRoute } from "./useActiveTripRoute";
import { useVehicleActiveDevice } from "./useVehicleActiveDevice";
import { useVehiclePosition } from "./useVehiclePosition";
import { VehicleMapPanel } from "./VehicleMapPanel";
import { VehicleOperationsHeader } from "./VehicleOperationsHeader";
import styles from "./LiveTrackingPage.module.css";

/**
 * `/platform/tracking` + `/org/tracking` — Vehicle Operations console (Phase F7, evolved under
 * ADR-0028 "Unified Vehicle Operations", now redesigned into a compact-header + map/video
 * workspace console). Same shared component, same two routes, same nav entries as before — the
 * page resolves the selected vehicle's active Device/MDVR (ADR-0027) and, for eligible roles,
 * its live video. One vehicle selection stays the single source of truth for both capabilities;
 * nothing here duplicates the GPS WebSocket implementation (`useVehiclePosition`, reusing the
 * shared `useWebSocketChannel` unchanged) or the video session implementation
 * (`../video/useVideoSessionController`/`useMpegtsPlayer`, reused unchanged, one instance per
 * camera via `../video/CameraTile` — see `MultiCameraVideoPanel`'s own docstring).
 *
 * **Console redesign, not a new architecture.** The old large left "Vehicle" card is gone —
 * vehicle selection plus GPS/device/camera status now live in the compact
 * `VehicleOperationsHeader` above the workspace. The old single-camera `CameraPicker` +
 * `VideoPlayerPanel` pairing is gone from this page — Live Video now renders every camera the
 * resolved device reports, simultaneously, via `MultiCameraVideoPanel`. Every underlying data
 * source, hook, and authorization check below is unchanged from before this redesign.
 *
 * **The device-status chip renders for every role that reaches this page.**
 * `fleet_device.devices.read` is already held by Founder/Regional Manager/Support Staff, not
 * just Org Admin, so this half needed no new grant and makes no new authorization decision — an
 * unauthorized caller's own `GET /vehicles/{id}/device-assignment`/`GET /devices/{id}` calls
 * simply fail server-side (`useVehicleActiveDevice`'s own `"error"` status), exactly like every
 * other query in this frontend.
 *
 * **The video sub-panel (multi-camera grid, Start/Stop Live) is gated to
 * `founder`/`regional_manager`/`support_staff`/`org_admin` (ADR-0029)** — presentation-only
 * gating (`.claude/rules/frontend.md` #2), aligned to the role set D5
 * (`core.policies.video_access.VideoAccessPolicy._VIDEO_ELIGIBLE_ROLES`) already treats as
 * eligible on the web dashboard (D5 also lists `Role.PARENT`, ADR-0026, but Parent has no web
 * login at all — `.claude/rules/frontend.md` #4 — so it's structurally excluded here, not a new
 * decision). `enforce_d5`/`require_permission` remain the only real gate, invoked exactly where
 * they already are for `/video/*` — showing or hiding this section changes nothing about what
 * the server will accept from a given caller.
 *
 * **Vehicle -> Device is resolved exclusively through `useVehicleActiveDevice`**
 * (`GET /vehicles/{id}/device-assignment` then `GET /devices/{device_id}`, ADR-0027) — never
 * inferred from a GPS position's `device_id`. `useVehiclePosition` carries no `device_id` in its
 * own return shape at all, so there is nothing here to fall back to even by accident.
 */
/** ADR-0029: the web-dashboard video-eligible role set — mirrors D5's own
 * `_VIDEO_ELIGIBLE_ROLES` minus `Role.PARENT` (mobile-only, no web login at all). Kept as a
 * `Set` rather than inline role-string comparisons so this is the single place a future role
 * change would need to touch. */
const VIDEO_ELIGIBLE_WEB_ROLES = new Set<Role>([
  "founder",
  "regional_manager",
  "support_staff",
  "org_admin",
]);

export function LiveTrackingPage() {
  usePageHeader("Live Tracking", "Real-time vehicle position, device status, and live video");
  const canSeeVideo = useAuthStore(
    (s) => s.principal !== null && VIDEO_ELIGIBLE_WEB_ROLES.has(s.principal.role),
  );

  const [selectedVehicleId, setSelectedVehicleId] = useState<string>("");

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "tracking-picker"],
    queryFn: () => listVehiclesForTracking(""),
    staleTime: 60_000,
  });

  const gps = useVehiclePosition(selectedVehicleId);
  const { routeStops } = useActiveTripRoute(selectedVehicleId);
  const activeDevice = useVehicleActiveDevice(selectedVehicleId);

  const position = gps.livePosition
    ? gps.livePosition
    : gps.snapshotQuery.data
      ? {
          lat: gps.snapshotQuery.data.latitude,
          lng: gps.snapshotQuery.data.longitude,
          headingDeg: gps.snapshotQuery.data.headingDeg,
        }
      : null;

  const mapHeaderStatus =
    selectedVehicleId === "" ? undefined : (
      <div className={styles.mapHeaderStatus}>
        {gps.wsStatus === "open" && !gps.isAuthOrPolicyClose ? (
          <LiveIndicator>Live</LiveIndicator>
        ) : (
          <span className={styles.disconnected}>
            <WifiOff size={14} />
            {gps.isAuthOrPolicyClose ? "Not authorized to track this vehicle" : "Connecting…"}
          </span>
        )}
        {gps.livePosition && (
          <span className={styles.lastUpdate}>
            Last update {new Date(gps.livePosition.eventTime).toLocaleTimeString()}
          </span>
        )}
      </div>
    );

  return (
    <div className={styles.page}>
      <VehicleOperationsHeader
        vehicles={vehiclesQuery.data ?? []}
        vehiclesLoading={vehiclesQuery.isLoading}
        selectedVehicleId={selectedVehicleId}
        onSelectVehicle={setSelectedVehicleId}
        gps={gps}
        deviceStatus={activeDevice.status}
        device={activeDevice.device}
        showCameraChip={canSeeVideo}
      />

      <div className={clsx(styles.workspace, !canSeeVideo && styles.workspaceMapOnly)}>
        <VehicleMapPanel
          vehicleId={selectedVehicleId}
          position={position}
          hasKnownPosition={gps.hasKnownPosition}
          isPositionLoading={gps.snapshotQuery.isLoading}
          routeStops={routeStops}
          headerStatus={mapHeaderStatus}
        />

        {canSeeVideo && selectedVehicleId === "" && (
          <Card className={styles.videoStateCard}>
            <CardHeader title="Live Video" />
            <div className={styles.videoStateBody}>
              <EmptyState icon={<Video size={28} />} title="Select a vehicle to view its cameras" />
            </div>
          </Card>
        )}

        {canSeeVideo && selectedVehicleId !== "" && (
          <>
            {activeDevice.status === "loading" && (
              <Card className={styles.videoStateCard}>
                <CardHeader title="Live Video" />
                <div className={styles.videoStateBody}>
                  <Skeleton height={200} />
                </div>
              </Card>
            )}
            {activeDevice.status === "no-assignment" && (
              <Card className={styles.videoStateCard}>
                <CardHeader title="Live Video" />
                <div className={styles.videoStateBody}>
                  <EmptyState
                    icon={<Cpu size={28} />}
                    title="No device assigned"
                    description="Live video is unavailable until a device is assigned to this vehicle."
                  />
                </div>
              </Card>
            )}
            {activeDevice.status === "error" && (
              <Card className={styles.videoStateCard}>
                <CardHeader title="Live Video" />
                <div className={styles.videoStateBody}>
                  <EmptyState icon={<Cpu size={28} />} title="Could not load device" />
                </div>
              </Card>
            )}
            {activeDevice.status === "ready" && activeDevice.device && (
              <MultiCameraVideoPanel
                deviceId={activeDevice.device.id}
                cameras={activeDevice.device.cameras}
                deviceOnline={activeDevice.device.isOnline}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
