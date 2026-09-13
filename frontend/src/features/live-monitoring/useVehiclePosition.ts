import { useEffect, useState } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useToast } from "../../shared/components/Toast/toastStore";
import { useWebSocketChannel } from "../../shared/hooks/useWebSocket";
import { getLatestVehiclePosition, type TrackingWsMessage, type VehiclePosition } from "./api";

const UNAUTHENTICATED_CLOSE_CODE = 4401;
const FORBIDDEN_CLOSE_CODE = 4403;

/**
 * Root-cause fix (RAAD Live Tracking wrong-location investigation) — no approved document
 * specifies a live/stale threshold for this UI, so this is a flagged, deliberately generous
 * constant (mirrors `tracking.events.subscribers._EVENT_COOLDOWN_SECONDS`'s own "documented but
 * unspecified by any approved doc" precedent): a real device in this environment reports roughly
 * every 20s, so 2 minutes tolerates several missed reports before the badge flips to "Stale"
 * rather than flickering on ordinary network jitter.
 */
export const GPS_LIVE_THRESHOLD_MS = 2 * 60 * 1000;

/** How often `gpsFixStatus` is re-evaluated against the current time with no new data — without
 * this, "Live" would only ever flip to "Stale" on the next unrelated re-render (the next
 * position/snapshot/status change), which may never come once a device has gone quiet. */
const GPS_STATUS_TICK_MS = 15_000;

export interface LivePosition {
  lat: number;
  lng: number;
  headingDeg: number;
  eventTime: string;
}

/** The most recent live signal, valid or not — distinct from `LivePosition` (the last known
 * GOOD position): this is updated on *every* `/ws/tracking` frame for the subscribed vehicle,
 * so a currently-invalid-fix report is visible even though it never moves `livePosition`. */
export interface GpsSignal {
  isGpsValid: boolean;
  eventTime: string;
}

export type GpsFixStatus = "live" | "stale" | "no_fix";

export interface UseVehiclePositionResult {
  wsStatus: "connecting" | "open" | "closed";
  isAuthOrPolicyClose: boolean;
  /** The last known GOOD (valid-fix) position — seeded from the REST snapshot and updated only
   * by a live WS frame whose own `is_gps_valid !== false`. Root-cause fix: previously this held
   * whatever the *most recent* WS frame said, valid or not, which is exactly how an
   * implausible/stale coordinate (e.g. this vendor hardware's cached Shenzhen factory fix) could
   * reach the map as if it were the vehicle's current position. */
  livePosition: LivePosition | null;
  snapshotQuery: UseQueryResult<VehiclePosition | null>;
  hasKnownPosition: boolean;
  /** Root-cause fix — see `deriveGpsFixStatus`'s own docstring for the exact state machine this
   * drives (`VehicleOperationsHeader`'s "GPS" chip, `VehicleMapPanel`'s overlay). */
  gpsFixStatus: GpsFixStatus;
  /** The most recent live signal regardless of validity — exposed so a caller can show
   * "Waiting for valid GPS position" copy distinct from "no data at all yet". */
  lastGpsSignal: GpsSignal | null;
}

/**
 * Root-cause fix (RAAD Live Tracking wrong-location investigation) — a pure, unit-testable
 * derivation of what the "GPS" chip/badge should say. Three states:
 *
 * - **`"live"`**: a valid-fix position is known and fresh (within `GPS_LIVE_THRESHOLD_MS`).
 * - **`"no_fix"`**: the device is actively reporting (a live frame arrived recently) but its
 *   most recent report carries no confirmed GPS fix — never silently presented as "Live" (this
 *   is the exact symptom this whole investigation started from).
 * - **`"stale"`**: a valid-fix position is known but has aged past the live threshold with no
 *   fresher valid — or invalid — signal since; the marker still shows this last-known-good
 *   position, just labeled honestly.
 *
 * Nothing here is ever inferred from silence beyond simple time comparison — no fake position is
 * invented, and an invalid-fix signal never overrides a *fresher* valid position (a device
 * cannot un-report a fix it already confirmed moments ago just because one bad reading arrived).
 */
export function deriveGpsFixStatus(params: {
  livePosition: LivePosition | null;
  lastSignal: GpsSignal | null;
  nowMs: number;
}): GpsFixStatus {
  const { livePosition, lastSignal, nowMs } = params;

  if (lastSignal && !lastSignal.isGpsValid) {
    const signalTimeMs = new Date(lastSignal.eventTime).getTime();
    const signalIsFresh = nowMs - signalTimeMs < GPS_LIVE_THRESHOLD_MS;
    const signalIsNewerThanLivePosition =
      !livePosition || signalTimeMs >= new Date(livePosition.eventTime).getTime();
    if (signalIsFresh && signalIsNewerThanLivePosition) {
      return "no_fix";
    }
  }

  if (livePosition) {
    const ageMs = nowMs - new Date(livePosition.eventTime).getTime();
    return ageMs < GPS_LIVE_THRESHOLD_MS ? "live" : "stale";
  }

  return "no_fix";
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
  const [lastGpsSignal, setLastGpsSignal] = useState<GpsSignal | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const snapshotQuery = useQuery({
    queryKey: ["tracking", "latest", vehicleId],
    queryFn: () => getLatestVehiclePosition(vehicleId),
    enabled: vehicleId !== "",
  });

  const { status, lastCloseCode, send } = useWebSocketChannel<TrackingWsMessage>("/ws/tracking", {
    enabled: vehicleId !== "",
    onMessage: (message) => {
      if (message.type === "position" && message.vehicle_id === vehicleId) {
        // Defensive default, matching the backend's own `payload.get("is_gps_valid", True)`
        // fallback: a frame from a not-yet-updated backend build (or missing the field for any
        // other reason) is treated as valid, never silently downgraded to "No Fix".
        const isGpsValid = message.is_gps_valid !== false;
        setLastGpsSignal({ isGpsValid, eventTime: message.event_time });
        // Root-cause fix: a fix-invalid frame updates the GPS *signal* (above) so "No Fix" can
        // be shown, but must never move the position the map marker actually renders.
        if (isGpsValid) {
          setLivePosition({
            lat: message.lat,
            lng: message.lng,
            headingDeg: message.heading_deg,
            eventTime: message.event_time,
          });
        }
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
    setLastGpsSignal(null);
  }, [vehicleId]);

  // Root-cause fix: seeds `livePosition` from the REST snapshot once it resolves, so a page
  // load with no live WS frame yet still has a "last known good" position (and its real
  // timestamp) to show/derive staleness from — the snapshot is Redis-backed and, since this same
  // fix, only ever caches a valid-fix position (`RedisLatestPositionWriter`'s own gate), so no
  // extra validity check is needed here. Never overwrites an already-set `livePosition`: a live
  // WS frame that arrived first is always at least as fresh as this one-time snapshot fetch.
  useEffect(() => {
    if (snapshotQuery.data && livePosition === null) {
      setLivePosition({
        lat: snapshotQuery.data.latitude,
        lng: snapshotQuery.data.longitude,
        headingDeg: snapshotQuery.data.headingDeg,
        eventTime: snapshotQuery.data.eventTime,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshotQuery.data]);

  // Forces a re-evaluation of gpsFixStatus over time even with no new data — see this constant's
  // own docstring for why "Live" must eventually flip to "Stale" on its own.
  useEffect(() => {
    if (vehicleId === "") return;
    const id = setInterval(() => setNowMs(Date.now()), GPS_STATUS_TICK_MS);
    return () => clearInterval(id);
  }, [vehicleId]);

  const hasKnownPosition = livePosition !== null;
  const isAuthOrPolicyClose =
    lastCloseCode === UNAUTHENTICATED_CLOSE_CODE || lastCloseCode === FORBIDDEN_CLOSE_CODE;
  const gpsFixStatus = deriveGpsFixStatus({ livePosition, lastSignal: lastGpsSignal, nowMs });

  return {
    wsStatus: status,
    isAuthOrPolicyClose,
    livePosition,
    snapshotQuery,
    hasKnownPosition,
    gpsFixStatus,
    lastGpsSignal,
  };
}
