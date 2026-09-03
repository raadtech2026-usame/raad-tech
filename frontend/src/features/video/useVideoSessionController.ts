import { useEffect, useRef, useState, type RefObject } from "react";
import { useMutation } from "@tanstack/react-query";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import { requestLiveVideo, stopVideoSession, type VideoSession } from "./api";
import { useMpegtsPlayer, type UseMpegtsPlayerResult } from "./useMpegtsPlayer";

export type VideoSessionPhase =
  | "idle"
  | "requesting"
  | "connecting"
  | "connected"
  /** Decoded at least one frame, and the viewer socket is still open, but the picture has
   * stopped advancing (2026-09-02). A distinct phase rather than a flag so it flows through the
   * existing badge mapping and the grid's own "N/M Live" count automatically — a frozen tile
   * must never be counted as Live. See `useMpegtsPlayer`'s `stalled` for why this is measured
   * from the media element's own playback position. */
  | "stalled"
  | "stopped"
  | "unavailable"
  | "error";

export interface VideoRequestError {
  message: string;
  /** A missing `VideoProviderPort` on this deployment and a genuine unexpected error are
   * indistinguishable at the HTTP layer (both a 500 `INTERNAL_ERROR`, `video/api/routers.py`'s
   * own documented behavior) — treated as "unavailable," not claimed as certainly one or the
   * other. */
  unavailable: boolean;
}

export interface UseVideoSessionControllerResult {
  phase: VideoSessionPhase;
  requestError: VideoRequestError | null;
  player: UseMpegtsPlayerResult;
  videoRef: RefObject<HTMLVideoElement>;
  canStart: boolean;
  canStop: boolean;
  start: () => void;
  stop: () => Promise<void>;
}

// Phase 6 (2026-09-02) — bounded, backed-off auto-recovery from an unexpected relay WebSocket
// close. 3 attempts mirrors this codebase's own existing small-retry-budget precedent elsewhere
// (never unbounded).
//
// **Delays raised sharply, and the budget no longer resets on a momentary connect
// (2026-09-02, after live measurement against the physical bench unit).** The original 1.5s/3s/6s
// backoff was measured actively making the underlying failure worse: 24 of 125 sampled relay
// sessions died at exactly these three values, because each retry fired a fresh `0x9101` burst at
// an MDVR whose JT/T 808 acknowledgement latency was already degrading from ~0.2s to ~11s under
// exactly that load. Worse, the budget was restored the moment `player.state` touched
// `"connected"` even briefly - so a session that connected and immediately died reset the counter
// forever, turning a *bounded* 3-attempt policy into an unbounded reconnect loop in practice,
// which is precisely the behaviour observed live. A retry budget is only genuinely restored by a
// connection that proves itself STABLE (`RECONNECT_STABILITY_MS`), never by one that merely
// existed for an instant.
const RECONNECT_MAX_ATTEMPTS = 3;
const RECONNECT_BASE_DELAY_MS = 5000;
// How long a session must stay continuously "connected" before its retry budget is considered
// earned back. Comfortably longer than the relay's own 30s `ingest_timeout`, so a session that
// only ever survives to that timeout can never refill the budget it just spent.
const RECONNECT_STABILITY_MS = 45000;

/**
 * ADR-0028 §G: the video session lifecycle half of `VideoPage`, extracted unchanged in
 * behavior — `POST /video/live` / `POST /video/sessions/{id}/stop` request/teardown, the
 * `mpegts.js` player attachment (via the unchanged `useMpegtsPlayer`), and the phase state
 * machine. `deviceId`/`cameraId` are nullable so this same controller drives both the
 * standalone, device-first `VideoPage` (both become non-null once picked) and the unified
 * Vehicle Operations view, where `deviceId` is resolved by `useVehicleActiveDevice`
 * (`features/live-monitoring/`) and is `null` until that resolves or when no device is
 * assigned — `canStart` already accounts for either being `null`, so no caller needs to
 * duplicate that guard.
 *
 * D5/RBAC/tenant-scope enforcement is unchanged and entirely server-side
 * (`requestLiveVideo`/`stopVideoSession`, `features/video/api.ts`) — this hook only reacts to
 * the response/error `requestLiveVideo` already returns; it makes no authorization decision of
 * its own, regardless of which page calls it.
 *
 * **Auto-recovery (Phase 6, 2026-09-02).** Previously a session that closed unexpectedly (relay
 * crash, network blip, idle/ingest timeout) left `phase` permanently `"unavailable"` — the
 * relay's viewer token is single-use, so nothing could resume the *same* session, and this hook
 * made no attempt to request a fresh one on the operator's behalf (`useMpegtsPlayer`'s own
 * docstring: "No auto-reconnect... a fresh `POST /video/live` call is required after any
 * close"). That sentence is still true of the *transport* (mpegts.js/the WS token), but nothing
 * requires the *operator* to be the one who notices and re-clicks Start Live. This hook now does
 * that automatically — bounded (`RECONNECT_MAX_ATTEMPTS`), backed off, never for a
 * user-initiated stop, and paused (not consumed) while the tab is backgrounded (Page Visibility
 * API) so a hidden tab neither burns its retry budget nor fights the browser's own
 * background-tab throttling. Never reconnects an old/expired token — every retry is a brand-new
 * `requestLiveVideo` call, exactly like a manual restart, so there is never anything stale to
 * resume. Never creates a duplicate session — the pre-existing per-session cleanup effect below
 * already calls `ensureStopped` on the old session the instant `session` changes away from it
 * (including this hook's own `setSession(null)` here), so the dead session is torn down
 * server-side before (or concurrently with) the new one being requested.
 */
export function useVideoSessionController(
  deviceId: string | null,
  cameraId: string | null,
): UseVideoSessionControllerResult {
  const toast = useToast();
  const [session, setSession] = useState<VideoSession | null>(null);
  const [manuallyStopped, setManuallyStopped] = useState(false);
  const [requestError, setRequestError] = useState<VideoRequestError | null>(null);
  const stoppedSessionIdsRef = useRef<Set<string>>(new Set());
  const reconnectAttemptsRef = useRef(0);
  const reconnectScheduledRef = useRef(false);
  const startClickedAtRef = useRef<number | null>(null);

  const startMutation = useMutation({
    mutationFn: () => {
      // Phase 4 diagnostic instrumentation — timestamps the browser's own side of the startup
      // path (Start click -> POST /video/live -> response -> player "connected"), so the
      // 20-30s startup delay this phase investigates can be measured, not guessed at, without
      // needing a debugger attached. Deliberately `console.debug` (cheap, no PII, opt-in-visible
      // via DevTools) rather than a new telemetry dependency - this module has none today.
      startClickedAtRef.current = performance.now();
      // eslint-disable-next-line no-console
      console.debug("[video:startup] POST /video/live sent", { deviceId, cameraId });
      return requestLiveVideo(deviceId as string, cameraId as string);
    },
    onSuccess: (newSession) => {
      const elapsedMs = startClickedAtRef.current !== null
        ? Math.round(performance.now() - startClickedAtRef.current)
        : null;
      // eslint-disable-next-line no-console
      console.debug("[video:startup] session created, awaiting first frame", {
        sessionId: newSession.id,
        requestRoundTripMs: elapsedMs,
      });
      setSession(newSession);
      setManuallyStopped(false);
      setRequestError(null);
    },
    onError: (error: unknown) => {
      const apiError = error instanceof ApiError ? error : null;
      setRequestError({
        message: apiError?.message ?? "Could not start the video session.",
        unavailable: apiError?.status === 500,
      });
    },
  });

  async function ensureStopped(sessionId: string): Promise<void> {
    if (stoppedSessionIdsRef.current.has(sessionId)) return;
    stoppedSessionIdsRef.current.add(sessionId);
    try {
      await stopVideoSession(sessionId);
    } catch {
      // Best-effort teardown, mirroring `VideoApplicationService.stop_video_session`'s own
      // "end() still runs even if the vendor-side call fails" posture — a failed stop here must
      // never block the UI from resetting.
    }
  }

  // Tears down whatever session was open *before* this render's selection — covers unmount,
  // switching device/camera (the effect below nulls `session` out first), and starting a fresh
  // session (the new `session` object replaces the old one, so this cleanup fires for the old
  // one exactly once, guarded by `ensureStopped`'s own idempotency set).
  useEffect(() => {
    return () => {
      if (session && !manuallyStopped) {
        void ensureStopped(session.id);
      }
    };
  }, [session, manuallyStopped]);

  // Changing the selection abandons any session requested for the *previous* one — never keep
  // streaming camera A in the background while the picker shows camera B selected.
  useEffect(() => {
    setSession(null);
    setManuallyStopped(false);
    setRequestError(null);
  }, [deviceId, cameraId]);

  const streamUrl = session && !manuallyStopped ? session.streamUrl : null;
  const videoRef = useRef<HTMLVideoElement>(null);
  const player = useMpegtsPlayer(streamUrl, videoRef);

  // Phase 4 diagnostic instrumentation — the last leg of the startup path this phase
  // investigates: how long from a fresh session existing to mpegts.js actually reporting a
  // decoded frame (`MEDIA_INFO`, this hook's own "connected" signal).
  const loggedConnectedForSessionRef = useRef<string | null>(null);
  useEffect(() => {
    if (player.state !== "connected" || !session) return;
    if (loggedConnectedForSessionRef.current === session.id) return;
    loggedConnectedForSessionRef.current = session.id;
    const totalMs = startClickedAtRef.current !== null
      ? Math.round(performance.now() - startClickedAtRef.current)
      : null;
    // eslint-disable-next-line no-console
    console.debug("[video:startup] first frame decoded - video visible", {
      sessionId: session.id,
      totalStartupMs: totalMs,
    });
  }, [player.state, session]);

  // A *stable* recovery restores the retry budget - never a momentary one. Previously this
  // reset on any `"connected"` transition at all, which is what made the nominally-bounded
  // 3-attempt policy unbounded in practice (see RECONNECT_STABILITY_MS above): a session that
  // connected and died seconds later refilled the budget it had just spent, forever.
  useEffect(() => {
    if (player.state !== "connected") return;
    const timerId = window.setTimeout(() => {
      reconnectAttemptsRef.current = 0;
    }, RECONNECT_STABILITY_MS);
    return () => window.clearTimeout(timerId);
  }, [player.state]);

  // Phase 6 — auto-recovery from an unexpected close (see this hook's own docstring for the
  // full reasoning). `reconnectScheduledRef` guards against scheduling more than one pending
  // reconnect for the same "closed" occurrence (this effect can otherwise re-run for unrelated
  // reasons - e.g. `session` identity - while still `"closed"`).
  useEffect(() => {
    if (player.state !== "closed") {
      reconnectScheduledRef.current = false;
      return;
    }
    if (manuallyStopped || !session) return;
    if (reconnectScheduledRef.current) return;
    if (reconnectAttemptsRef.current >= RECONNECT_MAX_ATTEMPTS) return;
    if (deviceId === null || cameraId === null) return;

    reconnectScheduledRef.current = true;

    const attemptReconnect = (): void => {
      reconnectAttemptsRef.current += 1;
      // eslint-disable-next-line no-console
      console.debug("[video:reconnect] attempting auto-recovery", {
        attempt: reconnectAttemptsRef.current,
        maxAttempts: RECONNECT_MAX_ATTEMPTS,
      });
      // Triggers the pre-existing per-session cleanup effect above (`ensureStopped` on the old,
      // now-dead session) and clears the closed player's `streamUrl` before requesting a brand
      // new session - never reconnects the old (single-use, now-consumed) viewer token.
      setSession(null);
      startMutation.mutate();
    };

    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      // Don't consume a retry attempt (or reconnect at all) while backgrounded - wait for the
      // tab to become visible again, then reconnect once. Never fights the browser's own
      // background-tab timer throttling by polling.
      const onVisible = (): void => {
        if (document.visibilityState !== "visible") return;
        document.removeEventListener("visibilitychange", onVisible);
        attemptReconnect();
      };
      document.addEventListener("visibilitychange", onVisible);
      return () => document.removeEventListener("visibilitychange", onVisible);
    }

    const delay = RECONNECT_BASE_DELAY_MS * 2 ** reconnectAttemptsRef.current;
    const timeoutId = window.setTimeout(attemptReconnect, delay);
    return () => window.clearTimeout(timeoutId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player.state, manuallyStopped, session, deviceId, cameraId]);

  async function stop(): Promise<void> {
    if (!session) return;
    setManuallyStopped(true);
    await ensureStopped(session.id);
    toast.info("Session stopped", "The live video session has been stopped.");
  }

  function start(): void {
    startMutation.mutate();
  }

  function computePhase(): VideoSessionPhase {
    if (startMutation.isPending) return "requesting";
    if (requestError) return requestError.unavailable ? "unavailable" : "error";
    if (!session) return "idle";
    if (manuallyStopped) return "stopped";
    // A `null` streamUrl is permanent for this session (no VideoProviderPort bound on this
    // deployment) — `useMpegtsPlayer` never even attempts a connection in that case, so
    // `player.state` stays `"idle"` forever. Checked before the `player.state` branches below
    // so it can't be confused with the *transient* single-render `"idle"` a fresh session
    // legitimately passes through, one render, on its way to a real `"connecting"` (see
    // `VideoPlayerPanel`'s own docstring on why the video element must already be mounted by
    // the time `useMpegtsPlayer`'s effect runs) — this check doesn't touch that path at all.
    if (streamUrl === null) return "unavailable";
    // Checked before "connected": a stalled player is still `state === "connected"` (that state
    // latches on the first decoded frame and only leaves on error/close), so this is the only
    // place the distinction can be made.
    if (player.state === "connected") return player.stalled ? "stalled" : "connected";
    if (player.state === "error") return "error";
    // The relay's WebSocket close code (invalid/used token vs. session-not-active) isn't
    // recoverable through mpegts.js (see `useMpegtsPlayer`'s own docstring) — any
    // non-user-initiated close is treated the same, honest as "unavailable" rather than
    // fabricating a distinction this transport can no longer make.
    if (player.state === "closed") return "unavailable";
    return "connecting";
  }

  const phase = computePhase();
  const canStart =
    deviceId !== null &&
    cameraId !== null &&
    phase !== "requesting" &&
    phase !== "connecting" &&
    phase !== "connected" &&
    phase !== "stalled";
  const canStop = phase === "connecting" || phase === "connected" || phase === "stalled";

  return { phase, requestError, player, videoRef, canStart, canStop, start, stop };
}
