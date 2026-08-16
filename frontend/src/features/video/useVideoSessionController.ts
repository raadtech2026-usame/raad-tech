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

  const startMutation = useMutation({
    mutationFn: () => requestLiveVideo(deviceId as string, cameraId as string),
    onSuccess: (newSession) => {
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
    if (player.state === "connected") return "connected";
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
    phase !== "connected";
  const canStop = phase === "connecting" || phase === "connected";

  return { phase, requestError, player, videoRef, canStart, canStop, start, stop };
}
