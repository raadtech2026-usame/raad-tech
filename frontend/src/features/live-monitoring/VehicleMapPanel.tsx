import { useEffect, useRef, useState, type ReactNode } from "react";
import { Crosshair, MapPin, Radio } from "lucide-react";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { MapView } from "../../shared/map/MapView";
import type { MapProvider } from "../../shared/map/MapProvider";
import type { GpsFixStatus } from "./useVehiclePosition";
import { buildVehiclePopupHtml, createVehicleMarkerElement, updateVehicleMarkerFixStatus } from "./vehicleMarker";
import type { RouteStop } from "./api";
import styles from "./VehicleMapPanel.module.css";

const DEFAULT_CENTER = { lat: 2.0469, lng: 45.3182 }; // Mogadishu — this codebase's own target market.
const DEFAULT_ZOOM = 13;
const VEHICLE_MARKER_ID = "live-vehicle";
const ROUTE_SOURCE_ID = "active-trip-route";
const STOPS_SOURCE_ID = "active-trip-stops";

export interface MapPosition {
  lat: number;
  lng: number;
  headingDeg: number;
  /** Optional purely so every existing caller/test passing a bare `{lat,lng,headingDeg}` fixture
   * (predating this popup) keeps compiling unchanged — `LiveTrackingPage`'s own real
   * `gps.livePosition` always carries this, so in production the popup below always has it. */
  eventTime?: string;
}

export interface VehicleMapPanelProps {
  vehicleId: string;
  position: MapPosition | null;
  hasKnownPosition: boolean;
  /** Root-cause fix (RAAD Live Tracking wrong-location investigation) — colors the marker and
   * is passed straight to `createVehicleMarkerElement`; defaults to `"live"` only when a
   * position is present and the caller hasn't wired this yet (kept optional so this component's
   * existing callers/tests aren't forced to change all at once). */
  gpsFixStatus?: GpsFixStatus;
  /** True while the initial snapshot is still resolving — suppresses the "No live position
   * data" empty state from flashing before the first fetch settles, matching the original
   * `LiveTrackingPage`'s own `!snapshotQuery.isLoading` gate exactly. */
  isPositionLoading: boolean;
  /** Plate number, optionally combined with a label — the marker's hover popup title. Optional
   * (falls back to the raw `vehicleId`) so this component's existing callers/tests keep working
   * unchanged; a real caller's title resolving after the marker was first created still refreshes
   * the popup in place (see the marker effect below), never a permanently-stale fallback. */
  vehicleTitle?: string;
  /** The vehicle's current speed, shown in the popup — `null`/omitted hides that line entirely,
   * never a fabricated "0 km/h". */
  speedKph?: number | null;
  routeStops: RouteStop[] | null;
  /** GPS live/connecting/last-update indicator, computed by `LiveTrackingPage` from
   * `useVehiclePosition`'s own state — rendered in the card header (ADR-0028 evolution's "MAP ●
   * Live" header requirement) rather than duplicated here, since this component has no GPS
   * connection state of its own to derive it from. */
  headerStatus?: ReactNode;
}

/**
 * ADR-0028 §G: `LiveTrackingPage`'s map card — `MapView` plus the marker add/update and
 * route/stop-layer effects, presentational (`position`/`routeStops` as props) rather than
 * reading page-local state directly. Reused verbatim by both the standalone tracking page and
 * the unified Vehicle Operations view — this component itself has no video/device awareness at
 * all.
 *
 * **Camera "follow" behavior (root-cause fix, RAAD Live Tracking wrong-location investigation —
 * the camera-jump half of that investigation).** Previously called `provider.setCenter(...)` on
 * *every* position update unconditionally, which repeatedly stole the viewport out from under
 * anyone who had manually panned/zoomed — on top of, at the time, doing so for positions that
 * hadn't even been confirmed as a genuine GPS fix. Now: the camera only recenters automatically
 * while `followVehicle` is `true` (the default); `MapProvider.onUserPanOrZoom` flips it `false`
 * the instant the user drags/zooms/rotates by hand, and a "Recenter" control brings it back —
 * the exact "don't steal the camera; make following explicit" behavior requested. The marker
 * itself still always tracks the real position regardless of `followVehicle` — only the
 * *camera* respects it.
 */
export function VehicleMapPanel({
  vehicleId,
  position,
  hasKnownPosition,
  gpsFixStatus,
  isPositionLoading,
  vehicleTitle,
  speedKph,
  routeStops,
  headerStatus,
}: VehicleMapPanelProps) {
  const providerRef = useRef<MapProvider | null>(null);
  const markerAddedRef = useRef(false);
  const markerElementRef = useRef<HTMLDivElement | null>(null);
  const routeLayersAddedRef = useRef(false);
  const unsubscribeUserPanRef = useRef<(() => void) | null>(null);
  const [followVehicle, setFollowVehicle] = useState(true);

  // Switching vehicles clears the previous one's live marker and resumes following the newly
  // selected vehicle — covers both an explicit vehicle change and the page's own initial mount.
  useEffect(() => {
    markerAddedRef.current = false;
    markerElementRef.current = null;
    setFollowVehicle(true);
    const provider = providerRef.current;
    if (provider) {
      provider.removeMarker(VEHICLE_MARKER_ID);
    }
  }, [vehicleId]);

  // Renders the live/snapshot position as a marker — the "hot path" `MapProvider.updateMarker`'s
  // own docstring names. The marker's own position always tracks reality; only the camera
  // (below) respects `followVehicle`.
  //
  // Root-cause fix (vehicle-popup staleness investigation): the hover popup's fix-status/speed/
  // last-GPS text is recomputed on every run of this effect and pushed via
  // `MapProvider.updateMarkerPopup` — this effect's dependency array already includes every input
  // the popup reads (`gpsFixStatus` was already here for the marker's own initial color;
  // `vehicleTitle`/`speedKph` are added for the same reason), so a fix-status flip or the plate/
  // label resolving after the marker was first created both refresh the popup in place, without
  // ever recreating the marker.
  useEffect(() => {
    const provider = providerRef.current;
    if (!provider) return;

    // `position` ultimately originates from either a raw `JSON.parse(...) as T` WebSocket frame
    // (no runtime schema validation) or a REST response — a malformed/partial payload can carry
    // non-numeric values here at runtime despite the type. Mapbox's own `LngLat` constructor
    // throws "Invalid LngLat object: (NaN, NaN)" on exactly this input, so this guard turns a
    // silent, unrecoverable map crash into a plain skipped update.
    if (!position || !Number.isFinite(position.lat) || !Number.isFinite(position.lng)) return;

    const fixStatus = gpsFixStatus ?? "live";
    const title = vehicleTitle ?? vehicleId;
    // Only ever `undefined` for a pre-existing test fixture that omits `eventTime` (see
    // `MapPosition`'s own docstring) — `LiveTrackingPage`'s real `gps.livePosition` always has
    // it, so production always has a popup here.
    const popupHtml =
      position.eventTime !== undefined
        ? buildVehiclePopupHtml(
            { title, fixStatus, speedKph: speedKph ?? null, eventTime: position.eventTime },
            { popup: styles.popup, title: styles.popupTitle, status: styles.popupStatus, muted: styles.popupMuted },
          )
        : undefined;

    if (markerAddedRef.current) {
      provider.updateMarker(VEHICLE_MARKER_ID, { lat: position.lat, lng: position.lng }, position.headingDeg);
      if (popupHtml !== undefined) {
        provider.updateMarkerPopup(VEHICLE_MARKER_ID, popupHtml);
      }
    } else {
      const element = createVehicleMarkerElement({
        fixStatus,
        ariaLabel: "This vehicle's current position",
      });
      markerElementRef.current = element;
      provider.addMarker({
        id: VEHICLE_MARKER_ID,
        position: { lat: position.lat, lng: position.lng },
        headingDeg: position.headingDeg,
        element,
        popupHtml,
      });
      markerAddedRef.current = true;
    }

    if (followVehicle) {
      provider.setCenter({ lat: position.lat, lng: position.lng });
    }
    // `followVehicle` is intentionally included so clicking "Recenter" (which sets it back to
    // `true`) immediately re-centers on the current position, not only on the next GPS update.
  }, [position, followVehicle, gpsFixStatus, vehicleTitle, speedKph]);

  // Marker color reflects the current GPS fix state independently of position changes (e.g. a
  // "Live" vehicle going quiet and aging into "Stale" between GPS updates).
  useEffect(() => {
    if (markerElementRef.current && gpsFixStatus) {
      updateVehicleMarkerFixStatus(markerElementRef.current, gpsFixStatus);
    }
  }, [gpsFixStatus]);

  // Static route/stop overlay for the vehicle's current in-progress trip, if any.
  useEffect(() => {
    const provider = providerRef.current;
    if (!provider) return;

    if (routeLayersAddedRef.current) {
      provider.removeLayer(ROUTE_SOURCE_ID);
      provider.removeLayer(STOPS_SOURCE_ID);
      provider.removeSource(ROUTE_SOURCE_ID);
      provider.removeSource(STOPS_SOURCE_ID);
      routeLayersAddedRef.current = false;
    }

    if (!routeStops || routeStops.length === 0) return;

    const ordered = [...routeStops].sort((a, b) => a.sequenceNo - b.sequenceNo);
    provider.addGeoJsonSource({
      id: ROUTE_SOURCE_ID,
      data: {
        type: "Feature",
        properties: {},
        geometry: { type: "LineString", coordinates: ordered.map((s) => [s.longitude, s.latitude]) },
      },
    });
    provider.addLineLayer({ id: ROUTE_SOURCE_ID, sourceId: ROUTE_SOURCE_ID });
    provider.addGeoJsonSource({
      id: STOPS_SOURCE_ID,
      data: {
        type: "FeatureCollection",
        features: ordered.map((s) => ({
          type: "Feature",
          properties: { name: s.name },
          geometry: { type: "Point", coordinates: [s.longitude, s.latitude] },
        })),
      },
    });
    provider.addPointLayer({ id: STOPS_SOURCE_ID, sourceId: STOPS_SOURCE_ID });
    routeLayersAddedRef.current = true;
  }, [routeStops]);

  return (
    <Card className={styles.mapCard}>
      <CardHeader title="Map" action={headerStatus} />
      <div className={styles.mapArea}>
        <MapView
          center={DEFAULT_CENTER}
          zoom={DEFAULT_ZOOM}
          className={styles.map}
          onReady={(provider) => {
            providerRef.current = provider;
            unsubscribeUserPanRef.current?.();
            unsubscribeUserPanRef.current = provider.onUserPanOrZoom(() => setFollowVehicle(false));
          }}
        />
        {vehicleId !== "" && hasKnownPosition && (
          <button
            type="button"
            className={followVehicle ? styles.followButtonActive : styles.followButton}
            onClick={() => setFollowVehicle(true)}
            disabled={followVehicle}
            aria-pressed={followVehicle}
          >
            <Crosshair size={14} aria-hidden="true" />
            {followVehicle ? "Following" : "Recenter"}
          </button>
        )}
        {vehicleId === "" && (
          <div className={styles.overlay}>
            <EmptyState icon={<MapPin size={28} />} title="Select a vehicle to start tracking" />
          </div>
        )}
        {vehicleId !== "" && !isPositionLoading && !hasKnownPosition && (
          <div className={styles.overlay}>
            <EmptyState
              icon={<Radio size={28} />}
              title="No live position data"
              description="This vehicle hasn't reported a position yet."
            />
          </div>
        )}
      </div>
    </Card>
  );
}
