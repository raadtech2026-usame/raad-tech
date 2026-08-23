import { useEffect, useMemo, useRef, useState } from "react";
import { Bus, Radio } from "lucide-react";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import { MapView } from "../../shared/map/MapView";
import type { MapProvider } from "../../shared/map/MapProvider";
import { FleetVehicleTracker } from "./FleetVehicleTracker";
import type { LivePosition } from "./useVehiclePosition";
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

function markerTooltip(vehicle: OnlineVehicle, position: { speedKph: number | null }): string {
  const lines = [vehicle.label ? `${vehicle.plateNo} — ${vehicle.label}` : vehicle.plateNo, "Online"];
  if (position.speedKph !== null) {
    lines.push(`${position.speedKph} km/h`);
  }
  lines.push("Click to view this vehicle");
  return lines.join("\n");
}

function createMarkerElement(vehicle: OnlineVehicle, onClick: () => void): HTMLDivElement {
  const el = document.createElement("div");
  el.className = styles.marker;
  el.setAttribute("role", "button");
  el.setAttribute("tabindex", "0");
  el.setAttribute("aria-label", `${vehicle.label ?? vehicle.plateNo} — click to view`);
  el.addEventListener("click", onClick);
  el.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onClick();
    }
  });
  return el;
}

interface ResolvedPosition {
  lat: number;
  lng: number;
  headingDeg?: number;
  speedKph: number | null;
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
 * polling (ADR-0031's own scalability analysis).
 */
export function FleetMapPanel({ vehicles, totalOnline, isLoading, onSelectVehicle }: FleetMapPanelProps) {
  const providerRef = useRef<MapProvider | null>(null);
  const markerElementsRef = useRef<Map<string, HTMLDivElement>>(new Map());
  const [livePositions, setLivePositions] = useState<Record<string, LivePosition>>({});
  const hasFitBoundsRef = useRef(false);

  // A fresh fleet-map mount (or a changed vehicle set) never carries over the previous set's
  // live positions — avoids showing a stale marker position under a vehicle id that has since
  // dropped off the online set.
  useEffect(() => {
    setLivePositions({});
    hasFitBoundsRef.current = false;
  }, [vehicles]);

  const handlePositionChange = (vehicleId: string, position: LivePosition) => {
    setLivePositions((prev) => ({ ...prev, [vehicleId]: position }));
  };

  // Effective position per vehicle: a live `/ws/tracking` frame once one has arrived, falling
  // back to the snapshot's own `position` (itself `null` today for every vehicle — ADR-0031's
  // disclosed JT808-writer gap — until that's separately closed).
  const resolvedPositions = useMemo(() => {
    const map = new Map<string, ResolvedPosition>();
    for (const vehicle of vehicles) {
      const live = livePositions[vehicle.vehicleId];
      if (live) {
        map.set(vehicle.vehicleId, {
          lat: live.lat,
          lng: live.lng,
          headingDeg: live.headingDeg,
          speedKph: vehicle.position?.speedKph ?? null,
        });
      } else if (vehicle.position) {
        map.set(vehicle.vehicleId, {
          lat: vehicle.position.latitude,
          lng: vehicle.position.longitude,
          headingDeg: vehicle.position.headingDeg ?? undefined,
          speedKph: vehicle.position.speedKph,
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
        existingElement.title = markerTooltip(vehicle, position);
      } else {
        const element = createMarkerElement(vehicle, () => onSelectVehicle(vehicle.vehicleId));
        element.title = markerTooltip(vehicle, position);
        provider.addMarker({
          id: vehicle.vehicleId,
          position: { lat: position.lat, lng: position.lng },
          headingDeg: position.headingDeg,
          element,
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
