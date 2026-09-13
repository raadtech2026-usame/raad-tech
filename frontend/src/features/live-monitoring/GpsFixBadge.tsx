import { Radio, RadioTower, WifiOff } from "lucide-react";
import { Badge } from "../../shared/components/Badge/Badge";
import type { GpsFixStatus } from "./useVehiclePosition";
import styles from "./GpsFixBadge.module.css";

export interface GpsFixBadgeProps {
  status: GpsFixStatus;
}

/**
 * Root-cause fix (RAAD Live Tracking wrong-location investigation) — the single place this
 * frontend renders a GPS fix state, shared by `VehicleOperationsHeader`'s "GPS" chip and
 * `LiveTrackingPage`'s map-card header, so the two can never drift into showing contradictory
 * labels for the same `gpsFixStatus`. Deliberately distinct from the WebSocket-connectivity
 * indicator (`WifiOff`/"Connecting…"/"Not authorized" — the *socket's* own state) — this badge
 * only ever renders once that socket is genuinely open, and answers a different question: "is
 * the position on screen actually live," not "is the connection up."
 */
export function GpsFixBadge({ status }: GpsFixBadgeProps) {
  if (status === "live") {
    return (
      <Badge variant="success" dot pulsing>
        <Radio size={12} className={styles.icon} aria-hidden="true" />
        Live
      </Badge>
    );
  }
  if (status === "no_fix") {
    return (
      <Badge variant="warning" dot>
        <RadioTower size={12} className={styles.icon} aria-hidden="true" />
        No Fix
      </Badge>
    );
  }
  return (
    <Badge variant="neutral" dot>
      <WifiOff size={12} className={styles.icon} aria-hidden="true" />
      Stale
    </Badge>
  );
}
