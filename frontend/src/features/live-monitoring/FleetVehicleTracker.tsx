import { useEffect } from "react";
import { useVehiclePosition, type LivePosition } from "./useVehiclePosition";

export interface FleetVehicleTrackerProps {
  vehicleId: string;
  onPositionChange: (vehicleId: string, position: LivePosition) => void;
}

/**
 * ADR-0031 (All Vehicles fleet-map mode) — renders nothing; exists purely to hold one
 * independent `useVehiclePosition` instance (and so, one independent `/ws/tracking`
 * WebSocket connection) per online vehicle. Mirrors `features/video/CameraTile.tsx`'s exact
 * shape for the identical "N independent instances of a single-item hook" problem: `CameraTile`
 * holds one `useVideoSessionController` per camera and reports its phase up via
 * `onPhaseChange`; this holds one `useVehiclePosition` per vehicle and reports its live
 * position up via `onPositionChange`, for `FleetMapPanel` to move that vehicle's marker.
 *
 * **Reuses `useVehiclePosition` completely unchanged** — no new GPS/WebSocket implementation
 * of any kind (`.claude/rules/frontend.md` #3, ADR-0028 §3's own "do not duplicate the GPS
 * WebSocket implementation"). The one-active-subscription-per-connection backend rule
 * (`tracking/api/ws.py`) is exactly why this needs to be N separate component instances, each
 * with its own connection, rather than one hook subscribing to many vehicles at once — ADR-0031
 * records the scalability analysis behind capping how many of these ever mount at once.
 */
export function FleetVehicleTracker({ vehicleId, onPositionChange }: FleetVehicleTrackerProps) {
  const { livePosition } = useVehiclePosition(vehicleId);

  useEffect(() => {
    if (livePosition) {
      onPositionChange(vehicleId, livePosition);
    }
    // `onPositionChange` is a parent-owned callback whose identity may change across renders;
    // this effect only needs to fire again when this tile's own position actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vehicleId, livePosition]);

  return null;
}
