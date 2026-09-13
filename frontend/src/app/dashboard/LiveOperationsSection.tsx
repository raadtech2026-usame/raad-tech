import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ArrowUpRight, Radio, WifiOff } from "lucide-react";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import { MapView } from "../../shared/map/MapView";
import type { MapProvider } from "../../shared/map/MapProvider";
import { getPlatformStats, type PlatformStats } from "../../features/platform-analytics/api";
import { getVehicle } from "../../features/fleet-devices/vehicles/api";
import { useVehiclePosition } from "../../features/live-monitoring/useVehiclePosition";
import { buildVehiclePopupHtml, createVehicleMarkerElement, updateVehicleMarkerFixStatus } from "../../features/live-monitoring/vehicleMarker";
import { useTripsInProgress, useVehicleStatusCounts } from "./hooks";
import styles from "./LiveOperationsSection.module.css";

const DEFAULT_CENTER = { lat: 2.0469, lng: 45.3182 }; // Mogadishu, matching LiveTrackingPage's own default.
const DEFAULT_ZOOM = 10;
const VEHICLE_MARKER_ID = "dashboard-preview-vehicle";

const numberFormatter = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

/**
 * "Live Operations" — a stat strip plus a compact live map preview. The strip's three counts are
 * ordinary REST polls (`staleTime` 30-60s), not WebSocket-pushed, so they render as plain numbers
 * rather than `LiveIndicator`/`Badge pulsing` — both components' own docstrings reserve that
 * blinking-dot treatment for genuinely real-time state, and using it here would misrepresent a
 * 30-60-second-old count as instantaneous.
 *
 * The map preview *is* genuinely live: it subscribes to the first vehicle currently on an
 * in-progress trip (found via `useTripsInProgress`, the same one query already backing the
 * "trips in progress" stat — no second lookup). **Root-cause fix (Dashboard/Live Operations
 * China-Shenzhen investigation):** this previously hand-rolled its own `/ws/tracking` subscribe
 * and blindly rendered every position frame's `lat`/`lng`, with no `is_gps_valid` check and no
 * REST-snapshot seeding — exactly the pre-fix bug `useVehiclePosition` (`live-monitoring`) already
 * closed for `LiveTrackingPage`/`VehicleMapPanel`, so this preview could still show a device's
 * stale/invalid factory fix (e.g. Shenzhen) even after that fix shipped. Now reuses
 * `useVehiclePosition` directly — the same authoritative last-known-good/`gpsFixStatus` state
 * machine, not a second, drifted copy of it. When no trip is currently in progress, this shows an
 * honest empty state rather than a stale or fabricated marker — the same posture `LiveTrackingPage`
 * already established for "no known position yet."
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
  const gps = useVehiclePosition(vehicleId ?? "");
  const navigate = useNavigate();
  const providerRef = useRef<MapProvider | null>(null);
  const markerAddedRef = useRef(false);
  const markerElementRef = useRef<HTMLDivElement | null>(null);

  // Minimal plate/label lookup for the popup's title — the only vehicle metadata this section
  // doesn't already have (`useTripsInProgress` only carries the id). Falls back to the raw id
  // below if this hasn't resolved yet, never blocking the marker on it.
  const vehicleQuery = useQuery({
    queryKey: ["vehicles", "dashboard-preview", vehicleId],
    queryFn: () => getVehicle(vehicleId as string),
    enabled: vehicleId !== null,
    staleTime: 60_000,
  });

  useEffect(() => {
    markerAddedRef.current = false;
    markerElementRef.current = null;
    providerRef.current?.removeMarker(VEHICLE_MARKER_ID);
  }, [vehicleId]);

  // Same professional RAAD bus marker + "vehicle info" hover popup as `LiveTrackingPage`/
  // `FleetMapPanel` (root-cause fix — Dashboard Live Operations marker-parity investigation):
  // this previously rendered a bare, generic `MapProvider.addMarker` pin with no popup at all,
  // a second, visually-drifted marker implementation.
  //
  // Root-cause fix (vehicle-popup staleness investigation): the popup's title/fix-status/speed/
  // last-GPS text is now recomputed on *every* run of this effect and pushed via
  // `MapProvider.updateMarkerPopup`, not just once at `addMarker` time — this effect's own
  // dependency array now includes every input the popup reads (not only `gps.livePosition`), so
  // a fix-status flip, a speed/timestamp change, or the vehicle plate/label resolving *after* the
  // marker was first created (a raw-id fallback used until then) all refresh the popup in place,
  // never requiring the marker itself to be removed/recreated.
  useEffect(() => {
    const provider = providerRef.current;
    const position = gps.livePosition;
    if (!provider || !position) return;
    // Same defensive guard `VehicleMapPanel` applies — an unvalidated position field could still
    // carry a non-finite value at runtime despite the type.
    if (!Number.isFinite(position.lat) || !Number.isFinite(position.lng)) return;

    const vehicle = vehicleQuery.data;
    const title = vehicle ? (vehicle.label ? `${vehicle.plateNo} — ${vehicle.label}` : vehicle.plateNo) : vehicleId!;
    const popupHtml = buildVehiclePopupHtml(
      {
        title,
        fixStatus: gps.gpsFixStatus,
        speedKph: gps.snapshotQuery.data?.speedKph ?? null,
        eventTime: position.eventTime,
        actionHint: "Click to open Live Tracking",
      },
      { popup: styles.popup, title: styles.popupTitle, status: styles.popupStatus, muted: styles.popupMuted },
    );

    if (markerAddedRef.current) {
      provider.updateMarker(VEHICLE_MARKER_ID, position, position.headingDeg);
      provider.updateMarkerPopup(VEHICLE_MARKER_ID, popupHtml);
    } else {
      const element = createVehicleMarkerElement({
        fixStatus: gps.gpsFixStatus,
        ariaLabel: `${title} — click to open Live Tracking`,
      });
      // Mirrors `FleetMapPanel`'s own click-to-navigate pattern: the listener lives on the
      // marker's own element (built-in `role="button"`/`tabindex`), not `MapProvider.onMarkerClick`.
      // Clicking navigates to the full Live Tracking page — there is no established way to deep
      // link that page to a pre-selected vehicle, so this goes exactly where the "View Live
      // Tracking" header link already does, never a fabricated capability.
      const goToLiveTracking = () => navigate("/platform/tracking");
      element.addEventListener("click", goToLiveTracking);
      element.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          goToLiveTracking();
        }
      });
      markerElementRef.current = element;
      provider.addMarker({
        id: VEHICLE_MARKER_ID,
        position,
        headingDeg: position.headingDeg,
        element,
        popupHtml,
      });
      markerAddedRef.current = true;
    }
    provider.setCenter(position);
  }, [gps.livePosition, gps.gpsFixStatus, gps.snapshotQuery.data, vehicleQuery.data, vehicleId, navigate]);

  // Marker color reflects the current GPS fix state independently of position changes, matching
  // `VehicleMapPanel`'s identical effect.
  useEffect(() => {
    if (markerElementRef.current) {
      updateVehicleMarkerFixStatus(markerElementRef.current, gps.gpsFixStatus);
    }
  }, [gps.gpsFixStatus]);

  const status = gps.wsStatus;
  const isAuthOrPolicyClose = gps.isAuthOrPolicyClose;

  return (
    <Card>
      <CardHeader
        title="Live Operations"
        subtitle="Trips, vehicles and devices right now"
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
