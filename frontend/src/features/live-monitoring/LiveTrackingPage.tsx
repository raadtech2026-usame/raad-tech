import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MapPin, Radio, WifiOff } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { FormField } from "../../shared/components/FormField/FormField";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../shared/components/Toast/toastStore";
import { useWebSocketChannel } from "../../shared/hooks/useWebSocket";
import { MapView } from "../../shared/map/MapView";
import type { MapProvider } from "../../shared/map/MapProvider";
import {
  getActiveTripRouteId,
  getLatestVehiclePosition,
  getRouteWithStops,
  listVehiclesForTracking,
  type TrackingWsMessage,
} from "./api";
import styles from "./LiveTrackingPage.module.css";

/** No stand-in/default position anywhere in this component — a marker only ever appears once a
 * real position (REST snapshot or a live WS frame) exists. This constant is only the map's own
 * *initial camera framing* before any vehicle is selected; it is never rendered as a vehicle. */
const DEFAULT_CENTER = { lat: 2.0469, lng: 45.3182 }; // Mogadishu — this codebase's own target market (RegisterDeviceWizard's own SIM-number placeholder is a +252 number).
const DEFAULT_ZOOM = 11;
const VEHICLE_MARKER_ID = "live-vehicle";
const ROUTE_SOURCE_ID = "active-trip-route";
const STOPS_SOURCE_ID = "active-trip-stops";

const UNAUTHENTICATED_CLOSE_CODE = 4401;
const FORBIDDEN_CLOSE_CODE = 4403;

interface LivePosition {
  lat: number;
  lng: number;
  headingDeg: number;
  eventTime: string;
}

/**
 * `/platform/tracking` + `/org/tracking` (Phase F7) — one shared component, matching every
 * other phase's two-dashboard pattern. Only a single vehicle is ever live at once: `/ws/tracking`
 * supports exactly one active subscription per connection (`tracking/api/ws.py`'s own docstring,
 * a deliberate backend simplification, not an oversight) — this page is the "per-vehicle detail
 * view" half of the roadmap's two F7 deliverables; a always-every-vehicle-live map was never the
 * shape the backend was built for.
 *
 * **Honest by construction, not just by intent**: this session's own device-onboarding-readiness
 * audit (`docs/architecture/device-onboarding-readiness-audit.md`) confirmed nothing in this
 * platform currently writes the Redis key `GET /tracking/vehicles/{id}/latest` reads, so that
 * snapshot will 404 ("no known position") for every vehicle in most environments — this page
 * shows that honestly rather than a fabricated marker, exactly like the roadmap's own F7 exit
 * criteria require. If a real device is streaming (or a real position event is manually
 * published), the live WS path below still renders it immediately, independent of that gap.
 */
export function LiveTrackingPage() {
  usePageHeader("Live Tracking", "Real-time vehicle position via the device gateway");
  const toast = useToast();

  const [selectedVehicleId, setSelectedVehicleId] = useState<string>("");
  const [livePosition, setLivePosition] = useState<LivePosition | null>(null);
  const providerRef = useRef<MapProvider | null>(null);
  const markerAddedRef = useRef(false);
  const routeLayersAddedRef = useRef(false);

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "tracking-picker"],
    queryFn: () => listVehiclesForTracking(""),
    staleTime: 60_000,
  });

  const snapshotQuery = useQuery({
    queryKey: ["tracking", "latest", selectedVehicleId],
    queryFn: () => getLatestVehiclePosition(selectedVehicleId),
    enabled: selectedVehicleId !== "",
  });

  const activeTripQuery = useQuery({
    queryKey: ["tracking", "active-trip", selectedVehicleId],
    queryFn: () => getActiveTripRouteId(selectedVehicleId),
    enabled: selectedVehicleId !== "",
  });

  const routeQuery = useQuery({
    queryKey: ["tracking", "route", activeTripQuery.data],
    queryFn: () => getRouteWithStops(activeTripQuery.data as string),
    enabled: !!activeTripQuery.data,
  });

  const { status, lastCloseCode, send } = useWebSocketChannel<TrackingWsMessage>("/ws/tracking", {
    enabled: selectedVehicleId !== "",
    onMessage: (message) => {
      if (message.type === "position" && message.vehicle_id === selectedVehicleId) {
        setLivePosition({
          lat: message.lat,
          lng: message.lng,
          headingDeg: message.heading_deg,
          eventTime: message.event_time,
        });
      } else if (message.type === "subscription_closed" && message.vehicle_id === selectedVehicleId) {
        toast.info("Tracking stopped", `Trip ended (${message.reason}) — showing the last known position.`);
      }
    },
  });

  // Sends (or re-sends, after any reconnect) the one subscribe frame this connection ever needs
  // — the backend replaces the prior subscription on the same connection when a new one arrives,
  // so switching vehicles needs no separate "unsubscribe" call.
  useEffect(() => {
    if (status === "open" && selectedVehicleId !== "") {
      send({ type: "subscribe", channel: "vehicle", vehicle_id: selectedVehicleId });
    }
    // `send` is intentionally omitted from the dependency array: it's a fresh function identity
    // every render of useWebSocketChannel, and including it would re-run this effect (re-sending
    // the same subscribe frame) on every unrelated re-render — only `status`/`selectedVehicleId`
    // transitions should trigger a (re-)subscribe.
  }, [status, selectedVehicleId]);

  // Switching vehicles clears the previous one's live marker/state rather than showing a stale
  // position under a new plate number.
  useEffect(() => {
    setLivePosition(null);
    markerAddedRef.current = false;
    const provider = providerRef.current;
    if (provider) {
      provider.removeMarker(VEHICLE_MARKER_ID);
    }
  }, [selectedVehicleId]);

  // Renders the live/snapshot position as a marker — the "hot path" `MapProvider.updateMarker`'s
  // own docstring names — whichever of the two (live WS frame, or the REST snapshot fetched on
  // selection) is the most recent known position.
  useEffect(() => {
    const provider = providerRef.current;
    if (!provider) return;

    const position = livePosition ?? (snapshotQuery.data ? {
      lat: snapshotQuery.data.latitude,
      lng: snapshotQuery.data.longitude,
      headingDeg: snapshotQuery.data.headingDeg,
    } : null);
    if (!position) return;

    if (markerAddedRef.current) {
      provider.updateMarker(VEHICLE_MARKER_ID, { lat: position.lat, lng: position.lng }, position.headingDeg);
    } else {
      provider.addMarker({ id: VEHICLE_MARKER_ID, position: { lat: position.lat, lng: position.lng }, headingDeg: position.headingDeg });
      markerAddedRef.current = true;
    }
    provider.setCenter({ lat: position.lat, lng: position.lng });
  }, [livePosition, snapshotQuery.data]);

  // Static route/stop overlay for the vehicle's current in-progress trip, if any — context only,
  // never live geofence *events* (this session's own audit confirmed geofence-crossing
  // generation is dead code anywhere in this platform today, so there is nothing live to show).
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

    const stops = routeQuery.data?.stops;
    if (!stops || stops.length === 0) return;

    const ordered = [...stops].sort((a, b) => a.sequenceNo - b.sequenceNo);
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
  }, [routeQuery.data]);

  const hasKnownPosition = livePosition !== null || snapshotQuery.data !== null;
  const isAuthOrPolicyClose = lastCloseCode === UNAUTHENTICATED_CLOSE_CODE || lastCloseCode === FORBIDDEN_CLOSE_CODE;

  return (
    <div className={styles.page}>
      <Card padded className={styles.sidebar}>
        <FormField label="Vehicle">
          {vehiclesQuery.isLoading ? (
            <Skeleton height={36} />
          ) : (
            <Select
              value={selectedVehicleId}
              onChange={(e) => setSelectedVehicleId(e.target.value)}
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
              {status === "open" && !isAuthOrPolicyClose ? (
                <LiveIndicator>Live</LiveIndicator>
              ) : (
                <span className={styles.disconnected}>
                  <WifiOff size={14} />
                  {isAuthOrPolicyClose ? "Not authorized to track this vehicle" : "Connecting…"}
                </span>
              )}
            </div>
            {livePosition && (
              <div className={styles.lastUpdate}>
                Last update: {new Date(livePosition.eventTime).toLocaleTimeString()}
              </div>
            )}
          </div>
        )}
      </Card>

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
          {selectedVehicleId === "" && (
            <div className={styles.overlay}>
              <EmptyState icon={<MapPin size={28} />} title="Select a vehicle to start tracking" />
            </div>
          )}
          {selectedVehicleId !== "" && !snapshotQuery.isLoading && !hasKnownPosition && (
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
    </div>
  );
}
