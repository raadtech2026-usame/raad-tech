import { useEffect, useRef } from "react";
import { MapPin, Radio } from "lucide-react";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { MapView } from "../../shared/map/MapView";
import type { MapProvider } from "../../shared/map/MapProvider";
import type { RouteStop } from "./api";
import styles from "./VehicleMapPanel.module.css";

const DEFAULT_CENTER = { lat: 2.0469, lng: 45.3182 }; // Mogadishu — this codebase's own target market.
const DEFAULT_ZOOM = 11;
const VEHICLE_MARKER_ID = "live-vehicle";
const ROUTE_SOURCE_ID = "active-trip-route";
const STOPS_SOURCE_ID = "active-trip-stops";

export interface MapPosition {
  lat: number;
  lng: number;
  headingDeg: number;
}

export interface VehicleMapPanelProps {
  vehicleId: string;
  position: MapPosition | null;
  hasKnownPosition: boolean;
  /** True while the initial snapshot is still resolving — suppresses the "No live position
   * data" empty state from flashing before the first fetch settles, matching the original
   * `LiveTrackingPage`'s own `!snapshotQuery.isLoading` gate exactly. */
  isPositionLoading: boolean;
  routeStops: RouteStop[] | null;
}

/**
 * ADR-0028 §G: `LiveTrackingPage`'s map card, extracted unchanged in behavior — `MapView` plus
 * the marker add/update and route/stop-layer effects, now presentational (`position`/
 * `routeStops` as props) rather than reading page-local state directly. Reused verbatim by both
 * the standalone tracking page and the unified Vehicle Operations view — this component itself
 * has no video/device awareness at all.
 */
export function VehicleMapPanel({
  vehicleId,
  position,
  hasKnownPosition,
  isPositionLoading,
  routeStops,
}: VehicleMapPanelProps) {
  const providerRef = useRef<MapProvider | null>(null);
  const markerAddedRef = useRef(false);
  const routeLayersAddedRef = useRef(false);

  // Switching vehicles clears the previous one's live marker — covers both an explicit vehicle
  // change and the page's own initial mount.
  useEffect(() => {
    markerAddedRef.current = false;
    const provider = providerRef.current;
    if (provider) {
      provider.removeMarker(VEHICLE_MARKER_ID);
    }
  }, [vehicleId]);

  // Renders the live/snapshot position as a marker — the "hot path" `MapProvider.updateMarker`'s
  // own docstring names.
  useEffect(() => {
    const provider = providerRef.current;
    if (!provider) return;

    // `position` ultimately originates from either a raw `JSON.parse(...) as T` WebSocket frame
    // (no runtime schema validation) or a REST response — a malformed/partial payload can carry
    // non-numeric values here at runtime despite the type. Mapbox's own `LngLat` constructor
    // throws "Invalid LngLat object: (NaN, NaN)" on exactly this input, so this guard turns a
    // silent, unrecoverable map crash into a plain skipped update.
    if (!position || !Number.isFinite(position.lat) || !Number.isFinite(position.lng)) return;

    if (markerAddedRef.current) {
      provider.updateMarker(VEHICLE_MARKER_ID, { lat: position.lat, lng: position.lng }, position.headingDeg);
    } else {
      provider.addMarker({
        id: VEHICLE_MARKER_ID,
        position: { lat: position.lat, lng: position.lng },
        headingDeg: position.headingDeg,
      });
      markerAddedRef.current = true;
    }
    provider.setCenter({ lat: position.lat, lng: position.lng });
  }, [position]);

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
    provider.addCircleLayer({ id: STOPS_SOURCE_ID, sourceId: STOPS_SOURCE_ID });
    routeLayersAddedRef.current = true;
  }, [routeStops]);

  return (
    <Card className={styles.mapCard}>
      <CardHeader title="Map" />
      <div className={styles.mapArea}>
        <MapView
          center={DEFAULT_CENTER}
          zoom={DEFAULT_ZOOM}
          className={styles.map}
          onReady={(provider) => {
            providerRef.current = provider;
          }}
        />
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
