import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Cpu, WifiOff } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { Badge } from "../../shared/components/Badge/Badge";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { FormField } from "../../shared/components/FormField/FormField";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { Button } from "../../shared/components/Button/Button";
import { useAuthStore } from "../../shared/stores/authStore";
import { CameraPicker } from "../video/CameraPicker";
import { VideoPlayerPanel } from "../video/VideoPlayerPanel";
import { useVideoSessionController } from "../video/useVideoSessionController";
import { listVehiclesForTracking } from "./api";
import { useActiveTripRoute } from "./useActiveTripRoute";
import { useVehicleActiveDevice } from "./useVehicleActiveDevice";
import { useVehiclePosition } from "./useVehiclePosition";
import { VehicleMapPanel } from "./VehicleMapPanel";
import styles from "./LiveTrackingPage.module.css";

/**
 * `/platform/tracking` + `/org/tracking` (Phase F7, evolved under ADR-0028 — Unified Vehicle
 * Operations). Same shared component, same two routes, same nav entries as before (ADR-0028
 * §A/§F: no new route, no backward-compatibility break) — the page now also resolves the
 * selected vehicle's active Device/MDVR (ADR-0027) and, for Org Admin, its live video. One
 * vehicle selection stays the single source of truth for both capabilities; nothing here
 * duplicates the GPS WebSocket implementation (`useVehiclePosition`, reusing the shared
 * `useWebSocketChannel` unchanged) or the video player implementation
 * (`../video/VideoPlayerPanel`/`useVideoSessionController`, reusing `useMpegtsPlayer`
 * unchanged) — both are extracted, reused pieces, not copies (ADR-0028 §G).
 *
 * **The device-status panel (terminal id, online/offline) renders for every role that reaches
 * this page.** `fleet_device.devices.read` is already held by Founder/Regional Manager/Support
 * Staff, not just Org Admin, so this half needed no new grant and makes no new authorization
 * decision — an unauthorized caller's own `GET /vehicles/{id}/device-assignment`/`GET /devices/
 * {id}` calls simply fail server-side (`useVehicleActiveDevice`'s own `"error"` status), exactly
 * like every other query in this frontend.
 *
 * **The video sub-panel (camera picker, player, Start/Stop) is Org-Admin-only** —
 * presentation-only gating (`.claude/rules/frontend.md` #2) mirroring exactly the reading
 * `navConfig.ts`'s own existing comment already gives for why no platform role sees a video nav
 * entry today. `enforce_d5`/`require_permission` remain the only real gate, invoked exactly
 * where they already are for `/video/*` — showing or hiding this section changes nothing about
 * what the server will accept from a given caller. Whether Platform Admin should ever get a real
 * video capability is deliberately left open by ADR-0028 (§ Non-goals) — this is not that
 * decision, and this page does not make it.
 *
 * **Vehicle -> Device is resolved exclusively through `useVehicleActiveDevice`**
 * (`GET /vehicles/{id}/device-assignment` then `GET /devices/{device_id}`, ADR-0027) — never
 * inferred from a GPS position's `device_id`. `useVehiclePosition` carries no `device_id` in its
 * own return shape at all, so there is nothing here to fall back to even by accident (ADR-0028
 * §C's own "reporting device ≠ currently assigned device" distinction).
 */
export function LiveTrackingPage() {
  usePageHeader("Live Tracking", "Real-time vehicle position, device status, and live video");
  const isOrgAdmin = useAuthStore((s) => s.principal?.role === "org_admin");

  const [selectedVehicleId, setSelectedVehicleId] = useState<string>("");
  const [selectedCameraId, setSelectedCameraId] = useState<string>("");

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

  const videoSession = useVideoSessionController(
    activeDevice.device?.id ?? null,
    selectedCameraId || null,
  );

  function handleVehicleChange(vehicleId: string): void {
    setSelectedVehicleId(vehicleId);
    setSelectedCameraId("");
  }

  return (
    <div className={styles.page}>
      <Card padded className={styles.sidebar}>
        <FormField label="Vehicle">
          {vehiclesQuery.isLoading ? (
            <Skeleton height={36} />
          ) : (
            <Select
              value={selectedVehicleId}
              onChange={(e) => handleVehicleChange(e.target.value)}
              aria-label="Vehicle"
            >
              <option value="">Select a vehicle</option>
              {(vehiclesQuery.data ?? []).map((vehicle) => (
                <option key={vehicle.id} value={vehicle.id}>
                  {vehicle.plateNo}
                  {vehicle.label ? ` — ${vehicle.label}` : ""}
                </option>
              ))}
            </Select>
          )}
        </FormField>

        {selectedVehicleId !== "" && (
          <div className={styles.statusPanel}>
            <div className={styles.statusRow}>
              {gps.wsStatus === "open" && !gps.isAuthOrPolicyClose ? (
                <LiveIndicator>Live</LiveIndicator>
              ) : (
                <span className={styles.disconnected}>
                  <WifiOff size={14} />
                  {gps.isAuthOrPolicyClose ? "Not authorized to track this vehicle" : "Connecting…"}
                </span>
              )}
            </div>
            {gps.livePosition && (
              <div className={styles.lastUpdate}>
                Last update: {new Date(gps.livePosition.eventTime).toLocaleTimeString()}
              </div>
            )}
          </div>
        )}
      </Card>

      <div className={styles.operationsGrid}>
        <VehicleMapPanel
          vehicleId={selectedVehicleId}
          position={position}
          hasKnownPosition={gps.hasKnownPosition}
          isPositionLoading={gps.snapshotQuery.isLoading}
          routeStops={routeStops}
        />

        {selectedVehicleId !== "" && (
          <div className={styles.sidePanel}>
            <Card padded className={styles.deviceCard}>
              <CardHeader title="Device" />
              <div className={styles.deviceBody}>
                {activeDevice.status === "loading" && <Skeleton height={48} />}
                {activeDevice.status === "no-assignment" && (
                  <EmptyState
                    icon={<Cpu size={28} />}
                    title="No device assigned"
                    description="This vehicle has no active device assignment."
                  />
                )}
                {activeDevice.status === "error" && (
                  <EmptyState icon={<Cpu size={28} />} title="Could not load device" />
                )}
                {activeDevice.status === "ready" && activeDevice.device && (
                  <div className={styles.deviceInfo}>
                    <span className={styles.deviceTerminalId}>{activeDevice.device.terminalId}</span>
                    <Badge
                      variant={activeDevice.device.isOnline ? "success" : "warning"}
                      dot
                      pulsing={activeDevice.device.isOnline}
                    >
                      {activeDevice.device.isOnline ? "Online" : "Offline"}
                    </Badge>
                  </div>
                )}
              </div>
            </Card>

            {isOrgAdmin && (
              <Card className={styles.videoCard}>
                <CardHeader
                  title="Live Video"
                  action={
                    videoSession.phase === "connected" || videoSession.phase === "connecting" ? (
                      <LiveIndicator>
                        {videoSession.phase === "connected" ? "Live" : "Connecting"}
                      </LiveIndicator>
                    ) : undefined
                  }
                />
                <div className={styles.videoBody}>
                  {activeDevice.status === "loading" && <Skeleton height={200} />}
                  {activeDevice.status === "no-assignment" && (
                    <EmptyState
                      icon={<Cpu size={28} />}
                      title="No device assigned"
                      description="Live video is unavailable until a device is assigned to this vehicle."
                    />
                  )}
                  {activeDevice.status === "error" && (
                    <EmptyState icon={<Cpu size={28} />} title="Could not load device" />
                  )}
                  {activeDevice.status === "ready" &&
                    activeDevice.device &&
                    (activeDevice.device.cameras.length === 0 ? (
                      <EmptyState icon={<Cpu size={28} />} title="No camera channels configured" />
                    ) : (
                      <>
                        <CameraPicker
                          cameras={activeDevice.device.cameras}
                          value={selectedCameraId}
                          onChange={setSelectedCameraId}
                        />
                        {/* `is_online` is a best-effort telemetry mirror (ADR-0020/0027), not an
                            authoritative gate — this is a visible hint only, it never disables
                            Start (ADR-0028 §D): the real authority is the backend's own
                            `POST /video/live` call. */}
                        {!activeDevice.device.isOnline && (
                          <Badge variant="warning" className={styles.offlineBadge}>
                            Device last reported offline — a live stream may fail.
                          </Badge>
                        )}
                        <div className={styles.videoActions}>
                          <Button
                            onClick={videoSession.start}
                            disabled={!videoSession.canStart}
                            loading={videoSession.phase === "requesting"}
                            fullWidth
                          >
                            Start Live
                          </Button>
                          <Button
                            onClick={videoSession.stop}
                            disabled={!videoSession.canStop}
                            variant="danger"
                            fullWidth
                          >
                            Stop
                          </Button>
                        </div>
                        <div className={styles.videoPlayerArea}>
                          <VideoPlayerPanel
                            phase={videoSession.phase}
                            requestError={videoSession.requestError}
                            player={videoSession.player}
                            videoRef={videoSession.videoRef}
                            idleTitle="Select a camera"
                            idleDescription="Choose one of this device's cameras, then press Start Live."
                          />
                        </div>
                      </>
                    ))}
                </div>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
