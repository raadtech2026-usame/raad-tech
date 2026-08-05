import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowUpRight, Radio, WifiOff } from "lucide-react";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import { useWebSocketChannel } from "../../shared/hooks/useWebSocket";
import { MapView } from "../../shared/map/MapView";
import type { MapProvider } from "../../shared/map/MapProvider";
import { getPlatformStats, type PlatformStats } from "../../features/platform-analytics/api";
import type { TrackingWsMessage } from "../../features/live-monitoring/api";
import { useTripsInProgress, useVehicleStatusCounts } from "./hooks";
import styles from "./LiveOperationsSection.module.css";

const DEFAULT_CENTER = { lat: 2.0469, lng: 45.3182 }; // Mogadishu, matching LiveTrackingPage's own default.
const DEFAULT_ZOOM = 10;
const VEHICLE_MARKER_ID = "dashboard-preview-vehicle";
const UNAUTHENTICATED_CLOSE_CODE = 4401;
const FORBIDDEN_CLOSE_CODE = 4403;

const numberFormatter = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

/**
 * "Live Operations" — a stat strip plus a compact live map preview. The strip's three counts are
 * ordinary REST polls (`staleTime` 30-60s), not WebSocket-pushed, so they render as plain numbers
 * rather than `LiveIndicator`/`Badge pulsing` — both components' own docstrings reserve that
 * blinking-dot treatment for genuinely real-time state, and using it here would misrepresent a
 * 30-60-second-old count as instantaneous.
 *
 * The map preview *is* genuinely live: it auto-subscribes to `/ws/tracking` for the first vehicle
 * currently on an in-progress trip (found via `useTripsInProgress`, the same one query already
 * backing the "trips in progress" stat — no second lookup), mirroring `LiveTrackingPage`'s exact
 * subscribe/marker-update pattern minus its vehicle picker and route overlay (out of scope for a
 * dashboard *preview* — "View Live Tracking" links to the full page for that). When no trip is
 * currently in progress, this shows an honest empty state rather than a stale or fabricated
 * marker — the same posture `LiveTrackingPage` already established for "no known position yet."
 */
export function LiveOperationsSection() {
  const trips = useTripsInProgress();
  const vehicles = useVehicleStatusCounts();
  const platformStats = useQuery<PlatformStats>({
    queryKey: ["platform-analytics-stats"],
    queryFn: getPlatformStats,
    staleTime: 60_000,
  });

  const vehicleId = trips.previewVehicleId;
  const [livePosition, setLivePosition] = useState<{ lat: number; lng: number; headingDeg: number } | null>(null);
  const providerRef = useRef<MapProvider | null>(null);
  const markerAddedRef = useRef(false);

  const { status, lastCloseCode, send } = useWebSocketChannel<TrackingWsMessage>("/ws/tracking", {
    enabled: vehicleId !== null,
    onMessage: (message) => {
      if (message.type === "position" && message.vehicle_id === vehicleId) {
        setLivePosition({ lat: message.lat, lng: message.lng, headingDeg: message.heading_deg });
      }
    },
  });

  useEffect(() => {
    if (status === "open" && vehicleId !== null) {
      send({ type: "subscribe", channel: "vehicle", vehicle_id: vehicleId });
    }
    // `send` intentionally omitted — see LiveTrackingPage's identical effect for why.
  }, [status, vehicleId]);

  useEffect(() => {
    setLivePosition(null);
    markerAddedRef.current = false;
    providerRef.current?.removeMarker(VEHICLE_MARKER_ID);
  }, [vehicleId]);

  useEffect(() => {
    const provider = providerRef.current;
    if (!provider || !livePosition) return;
    if (!Number.isFinite(livePosition.lat) || !Number.isFinite(livePosition.lng)) return;

    if (markerAddedRef.current) {
      provider.updateMarker(VEHICLE_MARKER_ID, livePosition, livePosition.headingDeg);
    } else {
      provider.addMarker({ id: VEHICLE_MARKER_ID, position: livePosition, headingDeg: livePosition.headingDeg });
      markerAddedRef.current = true;
    }
    provider.setCenter(livePosition);
  }, [livePosition]);

  const isAuthOrPolicyClose = lastCloseCode === UNAUTHENTICATED_CLOSE_CODE || lastCloseCode === FORBIDDEN_CLOSE_CODE;

  return (
    <Card>
      <CardHeader
        title="Live Operations"
        action={
          <Link to="/platform/tracking" className={styles.viewAll}>
            View Live Tracking <ArrowUpRight size={14} />
          </Link>
        }
      />
      <div className={styles.stripAndMap}>
        <div className={styles.strip}>
          <div className={styles.stat}>
            <span className={styles.statValue}>
              {trips.isLoading || trips.isError ? "—" : numberFormatter.format(trips.total)}
            </span>
            <span className={styles.statLabel}>Trips in progress</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statValue}>
              {vehicles.isLoading || vehicles.isError ? "—" : numberFormatter.format(vehicles.active)}
            </span>
            <span className={styles.statLabel}>Vehicles active</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statValue}>
              {platformStats.isLoading || platformStats.isError || !platformStats.data
                ? "—"
                : numberFormatter.format(platformStats.data.devices.online)}
            </span>
            <span className={styles.statLabel}>Devices online</span>
          </div>
        </div>

        <div className={styles.mapArea}>
          <MapView
            center={DEFAULT_CENTER}
            zoom={DEFAULT_ZOOM}
            className={styles.map}
            onReady={(provider) => {
              providerRef.current = provider;
            }}
          />
          {trips.isError && (
            <div className={styles.overlay}>
              <EmptyState icon={<Radio size={22} />} title="Could not check for active trips" />
            </div>
          )}
          {!trips.isError && vehicleId === null && !trips.isLoading && (
            <div className={styles.overlay}>
              <EmptyState
                icon={<Radio size={22} />}
                title="No vehicles on an active trip"
                description="The live map will show a vehicle here the moment a trip starts."
              />
            </div>
          )}
          {vehicleId !== null && (
            <div className={styles.statusChip}>
              {status === "open" && !isAuthOrPolicyClose ? (
                <LiveIndicator>Live</LiveIndicator>
              ) : (
                <span className={styles.disconnected}>
                  <WifiOff size={13} />
                  {isAuthOrPolicyClose ? "Not authorized" : "Connecting…"}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
