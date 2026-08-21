import { Bus, Cpu, Radio, Video, WifiOff } from "lucide-react";
import { Badge } from "../../shared/components/Badge/Badge";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import type { ActiveDevice, VehicleOption } from "./api";
import type { VehicleActiveDeviceStatus } from "./useVehicleActiveDevice";
import type { UseVehiclePositionResult } from "./useVehiclePosition";
import styles from "./VehicleOperationsHeader.module.css";

export interface VehicleOperationsHeaderProps {
  vehicles: VehicleOption[];
  vehiclesLoading: boolean;
  selectedVehicleId: string;
  onSelectVehicle: (vehicleId: string) => void;
  gps: Pick<UseVehiclePositionResult, "wsStatus" | "isAuthOrPolicyClose" | "livePosition">;
  deviceStatus: VehicleActiveDeviceStatus;
  device: ActiveDevice | null;
  /** Whether this session's role may reach live video at all (ADR-0029) — gates only the
   * Cameras chip, mirroring the same role check that gates `MultiCameraVideoPanel` itself; every
   * other chip here reflects `fleet_device.devices.read`, already held more broadly. */
  showCameraChip: boolean;
}

/**
 * The compact "what am I watching, right now" status bar that replaces the old large left
 * Vehicle card. A vehicle selector plus a row of status chips reusing exactly the same
 * `useVehiclePosition`/`useVehicleActiveDevice` data `LiveTrackingPage` already resolves — this
 * component makes no query and no authorization decision of its own.
 */
export function VehicleOperationsHeader({
  vehicles,
  vehiclesLoading,
  selectedVehicleId,
  onSelectVehicle,
  gps,
  deviceStatus,
  device,
  showCameraChip,
}: VehicleOperationsHeaderProps) {
  const selectedVehicle = vehicles.find((v) => v.id === selectedVehicleId) ?? null;
  const gpsLive = selectedVehicleId !== "" && gps.wsStatus === "open" && !gps.isAuthOrPolicyClose;
  const deviceOnline = deviceStatus === "ready" && device !== null && device.isOnline;
  const cameraCount = deviceStatus === "ready" && device !== null ? device.cameras.length : null;

  return (
    <div className={styles.header}>
      <div className={styles.vehiclePicker}>
        <span className={styles.vehicleIcon} aria-hidden="true">
          <Bus size={18} />
        </span>
        <div className={styles.vehiclePickerBody}>
          {vehiclesLoading ? (
            <Skeleton width={180} height={22} />
          ) : (
            <Select
              className={styles.vehicleSelect}
              value={selectedVehicleId}
              onChange={(e) => onSelectVehicle(e.target.value)}
              aria-label="Vehicle"
            >
              <option value="">Select a vehicle</option>
              {vehicles.map((vehicle) => (
                <option key={vehicle.id} value={vehicle.id}>
                  {vehicle.plateNo}
                  {vehicle.label ? ` — ${vehicle.label}` : ""}
                </option>
              ))}
            </Select>
          )}
          <span className={styles.vehicleHint}>
            {selectedVehicle ? "Vehicle Operations" : "Select a vehicle to begin"}
          </span>
        </div>
      </div>

      {selectedVehicleId !== "" && (
        <div className={styles.statChips}>
          <div className={styles.chip} data-testid="chip-gps">
            {gpsLive ? (
              <Radio size={14} className={styles.chipIconLive} />
            ) : (
              <WifiOff size={14} className={styles.chipIconMuted} />
            )}
            <span className={styles.chipLabel}>GPS</span>
            <Badge variant={gpsLive ? "success" : "neutral"} dot pulsing={gpsLive}>
              {gpsLive ? "Live" : gps.isAuthOrPolicyClose ? "Not authorized" : "Connecting"}
            </Badge>
          </div>

          <div className={styles.chip} data-testid="chip-device">
            <Cpu size={14} className={deviceOnline ? styles.chipIconLive : styles.chipIconMuted} />
            <span className={styles.chipLabel}>Device</span>
            {deviceStatus === "loading" && <Skeleton width={64} height={16} />}
            {deviceStatus === "no-assignment" && <Badge variant="neutral">No device</Badge>}
            {deviceStatus === "error" && <Badge variant="danger">Unavailable</Badge>}
            {deviceStatus === "ready" && device && (
              <>
                <Badge variant={device.isOnline ? "success" : "warning"} dot pulsing={device.isOnline}>
                  {device.isOnline ? "Online" : "Offline"}
                </Badge>
                <span className={styles.terminalId}>{device.terminalId}</span>
              </>
            )}
          </div>

          {showCameraChip && (
            <div className={styles.chip} data-testid="chip-cameras">
              <Video size={14} className={cameraCount ? styles.chipIconLive : styles.chipIconMuted} />
              <span className={styles.chipLabel}>Cameras</span>
              <Badge variant={cameraCount ? "info" : "neutral"}>
                {cameraCount === null ? "—" : cameraCount}
              </Badge>
            </div>
          )}

          {gps.livePosition && (
            <span className={styles.lastUpdate}>
              Last GPS update {new Date(gps.livePosition.eventTime).toLocaleTimeString()}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
