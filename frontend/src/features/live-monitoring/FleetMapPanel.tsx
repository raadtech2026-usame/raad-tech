import { useEffect, useMemo, useRef, useState } from "react";
import { Bus, Radio } from "lucide-react";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import { MapView } from "../../shared/map/MapView";
import type { MapProvider } from "../../shared/map/MapProvider";
import { FleetVehicleTracker } from "./FleetVehicleTracker";
import type { GpsFixStatus, LivePosition } from "./useVehiclePosition";
import { buildVehiclePopupHtml, createVehicleMarkerElement, updateVehicleMarkerFixStatus } from "./vehicleMarker";
import type { OnlineVehicle } from "./api";
import styles from "./FleetMapPanel.module.css";

const DEFAULT_CENTER = { lat: 2.0469, lng: 45.3182 }; // Mogadishu, matching VehicleMapPanel's own default.
const DEFAULT_ZOOM = 10;

export interface FleetMapPanelProps {
  vehicles: OnlineVehicle[];
  totalOnline: number;
  isLoading: boolean;
  /** A marker click resolves back to the single-vehicle Live Tracking mode — the same
   * `onSelectVehicle` the header's own vehicle picker calls. */
  onSelectVehicle: (vehicleId: string) => void;
}

function popupHtml(vehicle: OnlineVehicle, position: ResolvedPosition): string {
  const title = vehicle.label ? `${vehicle.plateNo} — ${vehicle.label}` : vehicle.plateNo;
  return buildVehiclePopupHtml(
    {
      title,
      fixStatus: position.fixStatus,
      speedKph: position.speedKph,
      eventTime: position.eventTime,
      actionHint: "Click to view this vehicle",
    },
    { popup: styles.popup, title: styles.popupTitle, status: styles.popupStatus, muted: styles.popupMuted },
  );
}

interface ResolvedPosition {
  lat: number;
  lng: number;
  headingDeg?: number;
  speedKph: number | null;
  eventTime: string;
  fixStatus: GpsFixStatus;
}

/**
 * ADR-0031 — the All Vehicles fleet-overview map. A distinct component from `VehicleMapPanel`
 * (kept completely unchanged for the individual-vehicle mode) rather than a shared component
 * with a mode switch, so single-vehicle behavior can never regress from fleet-mode changes.
 *
 * **Never touches video/camera state.** This component and everything it renders
 * (`FleetVehicleTracker`) has no import of `useVideoSessionController`/`useMpegtsPlayer`/
 * `CameraTile`/`MultiCameraVideoPanel` anywhere in its tree — All Vehicles mode structurally
 * cannot open a video session, not just by convention.
 *
 * **Realtime updates reuse the existing `/ws/tracking` infrastructure unchanged**: one
 * `FleetVehicleTracker` (one independent `useVehiclePosition` instance) per vehicle in the
 * capped online set the backend already returned — never a new WebSocket protocol, never REST
 * polling (ADR-0031's own scalability analysis). Each tracker also reports the vehicle's own
 * `GpsFixStatus` (root-cause fix, RAAD Live Tracking wrong-location investigation), which colors
 * that vehicle's marker exactly as `VehicleMapPanel`'s own marker is colored — a vehicle whose
 * device is reporting but has no genuine GPS fix is never shown identically to one with a live,
 * valid position.
 *
 * **No clustering** — ADR-0031's own scalability analysis capped this view at
 * `FLEET_OVERVIEW_MAX_ONLINE_VEHICLES` (100) precisely because RAAD's realistic per-organization
 * fleet size (tens to a couple hundred buses) never needs it; clustering is real added
 * complexity (expand-on-zoom behavior, cluster styling) this view's own scale doesn't justify —
 * revisit only if that cap is ever raised.
 */
export function FleetMapPanel({ vehicles, totalOnline, isLoading, onSelectVehicle }: FleetMapPanelProps) {
  const providerRef = useRef<MapProvider | null>(null);
  const markerElementsRef = useRef<Map<string, HTMLDivElement>>(new Map());
  const [livePositions, setLivePositions] = useState<
    Record<string, { position: LivePosition; fixStatus: GpsFixStatus }>
  >({});
  const hasFitBoundsRef = useRef(false);

  // A fresh fleet-map mount (or a changed vehicle set) never carries over the previous set's
  // live positions — avoids showing a stale marker position under a vehicle id that has since
  // dropped off the online set.
  useEffect(() => {
    setLivePositions({});
    hasFitBoundsRef.current = false;
  }, [vehicles]);

  const handlePositionChange = (
    vehicleId: string,
    position: LivePosition,
    fixStatus: GpsFixStatus,
  ) => {
    setLivePositions((prev) => ({ ...prev, [vehicleId]: { position, fixStatus } }));
  };

  // Effective position per vehicle: a live `/ws/tracking` frame once one has arrived, falling
  // back to the snapshot's own `position` (Redis-backed and, since the root-cause fix, always a
  // confirmed valid-fix reading when present — so a snapshot-only vehicle is shown "live" rather
  // than an invented intermediate state).
  const resolvedPositions = useMemo(() => {
    const map = new Map<string, ResolvedPosition>();
    for (const vehicle of vehicles) {
      const live = livePositions[vehicle.vehicleId];
      if (live) {
        map.set(vehicle.vehicleId, {
          lat: live.position.lat,
          lng: live.position.lng,
          headingDeg: live.position.headingDeg,
          speedKph: vehicle.position?.speedKph ?? null,
          eventTime: live.position.eventTime,
          fixStatus: live.fixStatus,
        });
      } else if (vehicle.position) {
        map.set(vehicle.vehicleId, {
          lat: vehicle.position.latitude,
          lng: vehicle.position.longitude,
          headingDeg: vehicle.position.headingDeg ?? undefined,
          speedKph: vehicle.position.speedKph,
          eventTime: vehicle.position.eventTime,
          fixStatus: "live",
        });
      }
    }
    return map;
  }, [vehicles, livePositions]);

  useEffect(() => {
    const provider = providerRef.current;
    if (!provider) return;

    const currentIds = new Set(resolvedPositions.keys());
    for (const staleId of markerElementsRef.current.keys()) {
      if (!currentIds.has(staleId)) {
        provider.removeMarker(staleId);
        markerElementsRef.current.delete(staleId);
      }
    }

    for (const vehicle of vehicles) {
      const position = resolvedPositions.get(vehicle.vehicleId);
      if (!position) continue;
      const existingElement = markerElementsRef.current.get(vehicle.vehicleId);
      if (existingElement) {
        provider.updateMarker(vehicle.vehicleId, { lat: position.lat, lng: position.lng }, position.headingDeg);
        updateVehicleMarkerFixStatus(existingElement, position.fixStatus);
        // Root-cause fix (vehicle-popup staleness investigation): previously the popup's speed/
        // fix-status/last-GPS text was set once, at `addMarker` time, and never touched again —
        // now refreshed on every position/status tick, in place, via `updateMarkerPopup`.
        provider.updateMarkerPopup(vehicle.vehicleId, popupHtml(vehicle, position));
      } else {
        const element = createVehicleMarkerElement({
          fixStatus: position.fixStatus,
          ariaLabel: `${vehicle.label ?? vehicle.plateNo} — click to view`,
        });
        element.addEventListener("click", () => onSelectVehicle(vehicle.vehicleId));
        element.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelectVehicle(vehicle.vehicleId);
          }
        });
        provider.addMarker({
          id: vehicle.vehicleId,
          position: { lat: position.lat, lng: position.lng },
          headingDeg: position.headingDeg,
          element,
          popupHtml: popupHtml(vehicle, position),
        });
        markerElementsRef.current.set(vehicle.vehicleId, element);
      }
    }

    if (!hasFitBoundsRef.current && resolvedPositions.size > 1) {
      let sw = { lat: Infinity, lng: Infinity };
      let ne = { lat: -Infinity, lng: -Infinity };
      for (const { lat, lng } of resolvedPositions.values()) {
        sw = { lat: Math.min(sw.lat, lat), lng: Math.min(sw.lng, lng) };
        ne = { lat: Math.max(ne.lat, lat), lng: Math.max(ne.lng, lng) };
      }
      provider.fitBounds({ sw, ne }, 60);
      hasFitBoundsRef.current = true;
    } else if (!hasFitBoundsRef.current && resolvedPositions.size === 1) {
      const only = resolvedPositions.values().next().value;
      if (only) provider.setCenter({ lat: only.lat, lng: only.lng });
      hasFitBoundsRef.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vehicles, resolvedPositions]);

  const onlineWithPosition = resolvedPositions.size;

  return (
    <Card className={styles.mapCard}>
      <CardHeader
        title="Fleet Overview"
        action={
          <div className={styles.headerStatus}>
            <LiveIndicator>{`${vehicles.length}/${totalOnline} vehicles`}</LiveIndicator>
          </div>
        }
      />
      <div className={styles.mapArea}>
        <MapView
          center={DEFAULT_CENTER}
          zoom={DEFAULT_ZOOM}
          className={styles.map}
          onReady={(provider) => {
            providerRef.current = provider;
          }}
        />
        {vehicles.map((vehicle) => (
          <FleetVehicleTracker
            key={vehicle.vehicleId}
            vehicleId={vehicle.vehicleId}
            onPositionChange={handlePositionChange}
          />
        ))}
        {!isLoading && vehicles.length === 0 && (
          <div className={styles.overlay}>
            <EmptyState icon={<Radio size={28} />} title="No vehicles are currently online" />
          </div>
        )}
        {!isLoading && vehicles.length > 0 && onlineWithPosition === 0 && (
          <div className={styles.overlay}>
            <EmptyState
              icon={<Bus size={28} />}
              title={`${vehicles.length} vehicle${vehicles.length === 1 ? "" : "s"} online`}
              description="Waiting for a live position update for each one."
            />
          </div>
        )}
      </div>
    </Card>
  );
}
