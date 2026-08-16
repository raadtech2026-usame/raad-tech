import { useEffect, useState } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useToast } from "../../shared/components/Toast/toastStore";
import { useWebSocketChannel } from "../../shared/hooks/useWebSocket";
import { getLatestVehiclePosition, type TrackingWsMessage, type VehiclePosition } from "./api";

const UNAUTHENTICATED_CLOSE_CODE = 4401;
const FORBIDDEN_CLOSE_CODE = 4403;

export interface LivePosition {
  lat: number;
  lng: number;
  headingDeg: number;
  eventTime: string;
}

export interface UseVehiclePositionResult {
  wsStatus: "connecting" | "open" | "closed";
  isAuthOrPolicyClose: boolean;
  livePosition: LivePosition | null;
  snapshotQuery: UseQueryResult<VehiclePosition | null>;
  hasKnownPosition: boolean;
}

/**
 * ADR-0028 §G: the GPS half of `LiveTrackingPage`, extracted unchanged in behavior — the
 * `GET /tracking/vehicles/{id}/latest` snapshot plus the `/ws/tracking` subscribe lifecycle,
 * exactly as before this extraction. Reuses the shared `useWebSocketChannel` primitive
 * (`shared/hooks/useWebSocket.ts`) unchanged — this hook adds no new WebSocket implementation of
 * its own (ADR-0028 §3's "do not duplicate the GPS WebSocket implementation").
 *
 * Deliberately returns no `device_id` of any kind — this hook's own contract is GPS only, so a
 * future caller cannot accidentally read a device identity out of it. `useVehicleActiveDevice`
 * (this same feature folder) is the only sanctioned source of a `device_id` (ADR-0028 §C).
 */
export function useVehiclePosition(vehicleId: string): UseVehiclePositionResult {
  const toast = useToast();
  const [livePosition, setLivePosition] = useState<LivePosition | null>(null);

  const snapshotQuery = useQuery({
    queryKey: ["tracking", "latest", vehicleId],
    queryFn: () => getLatestVehiclePosition(vehicleId),
    enabled: vehicleId !== "",
  });

  const { status, lastCloseCode, send } = useWebSocketChannel<TrackingWsMessage>("/ws/tracking", {
    enabled: vehicleId !== "",
    onMessage: (message) => {
      if (message.type === "position" && message.vehicle_id === vehicleId) {
        setLivePosition({
          lat: message.lat,
          lng: message.lng,
          headingDeg: message.heading_deg,
          eventTime: message.event_time,
        });
      } else if (message.type === "subscription_closed" && message.vehicle_id === vehicleId) {
        toast.info("Tracking stopped", `Trip ended (${message.reason}) — showing the last known position.`);
      }
    },
  });

  // Sends (or re-sends, after any reconnect) the one subscribe frame this connection ever needs
  // — the backend replaces the prior subscription on the same connection when a new one arrives,
  // so switching vehicles needs no separate "unsubscribe" call.
  useEffect(() => {
    if (status === "open" && vehicleId !== "") {
      send({ type: "subscribe", channel: "vehicle", vehicle_id: vehicleId });
    }
    // `send` is intentionally omitted from the dependency array: it's a fresh function identity
    // every render of useWebSocketChannel, and including it would re-run this effect (re-sending
    // the same subscribe frame) on every unrelated re-render — only `status`/`vehicleId`
    // transitions should trigger a (re-)subscribe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, vehicleId]);

  // Switching vehicles drops the previous one's live position rather than showing a stale
  // reading under a new plate number — the map-marker half of this reset lives in
  // `VehicleMapPanel` (map state, not GPS data, ADR-0028 §G's own split).
  useEffect(() => {
    setLivePosition(null);
  }, [vehicleId]);

  const hasKnownPosition = livePosition !== null || snapshotQuery.data !== null;
  const isAuthOrPolicyClose =
    lastCloseCode === UNAUTHENTICATED_CLOSE_CODE || lastCloseCode === FORBIDDEN_CLOSE_CODE;

  return { wsStatus: status, isAuthOrPolicyClose, livePosition, snapshotQuery, hasKnownPosition };
}
