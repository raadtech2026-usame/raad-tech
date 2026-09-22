import { useEffect, useRef, useState, type RefObject } from "react";
import { useMutation } from "@tanstack/react-query";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import {
  controlPlayback,
  requestPlaybackVideo,
  stopVideoSession,
  type PlaybackControlAction,
  type VideoSession,
} from "./api";
import { useMpegtsPlayer, type UseMpegtsPlayerResult } from "./useMpegtsPlayer";
import type { VideoRequestError, VideoSessionPhase } from "./useVideoSessionController";

export interface UsePlaybackSessionControllerResult {
  phase: VideoSessionPhase;
  requestError: VideoRequestError | null;
  player: UseMpegtsPlayerResult;
  videoRef: RefObject<HTMLVideoElement>;
  session: VideoSession | null;
  canStop: boolean;
  /** True while a transport command is in flight — the buttons disable, but the *picture* is
   * not claimed to have changed (see `control`). */
  isControlling: boolean;
  start: (windowStart: string, windowEnd: string) => void;
  stop: () => Promise<void>;
  control: (action: PlaybackControlAction, options?: { speed?: number; position?: string }) => void;
}

/**
 * ADR-0044 — the playback sibling of `useVideoSessionController`. Requests
 * `POST /video/playback`, attaches the same `mpegts.js` player to the relay's viewer URL, and
 * forwards transport commands to `POST /video/sessions/{id}/playback-control`. The MDVR is the
 * recording store throughout; nothing here downloads or stores a media byte, and the stream
 * reaches the browser from the relay exactly as a live one does.
 *
 * **Deliberately a separate hook, not an option on the live one.** Three of that hook's
 * behaviors are wrong for playback and would be silently harmful:
 *
 * 1. **No auto-reconnect.** The live hook re-requests a session when the relay socket closes.
 *    A playback session re-requested that way would restart the recording from the beginning of
 *    the window — the operator would silently lose their place, and each retry costs another
 *    `0x9201` on the cellular link. A closed playback session surfaces honestly as
 *    `"unavailable"`, and the operator decides whether to replay.
 * 2. **No stream-type switching.** `0x9201` carries its own stream/storage selectors; ADR-0043's
 *    main/sub grid logic has no meaning for a stored file.
 * 3. **The window is a start-time argument, not hook state.** The operator picks a segment and
 *    plays *it*; there is no "current selection" that should tear a session down mid-playback.
 *
 * **A successful `control` call means the command was sent, never that the tape moved
 * (ADR-0044 Consequences).** Seek/fast-forward support is firmware-dependent: the terminal
 * answers `0x9202` with an ordinary general result on the device plane, which never reaches this
 * response. The toast below therefore says the command was sent — it does not assert the new
 * playback state, and no local "paused"/"speed" flag is kept that could disagree with what the
 * device actually did.
 */
export function usePlaybackSessionController(
  deviceId: string | null,
  cameraId: string | null,
): UsePlaybackSessionControllerResult {
  const toast = useToast();
  const [session, setSession] = useState<VideoSession | null>(null);
  const [manuallyStopped, setManuallyStopped] = useState(false);
  const [requestError, setRequestError] = useState<VideoRequestError | null>(null);
  const stoppedSessionIdsRef = useRef<Set<string>>(new Set());

  const startMutation = useMutation({
    mutationFn: ({ windowStart, windowEnd }: { windowStart: string; windowEnd: string }) =>
      requestPlaybackVideo(deviceId as string, cameraId as string, windowStart, windowEnd),
    onSuccess: (newSession) => {
      setSession(newSession);
      setManuallyStopped(false);
      setRequestError(null);
    },
    onError: (error: unknown) => {
      const apiError = error instanceof ApiError ? error : null;
      setRequestError({
        message: apiError?.message ?? "Could not start playback.",
        unavailable: apiError?.status === 500,
      });
    },
  });

  const controlMutation = useMutation({
    mutationFn: ({
      action,
      options,
    }: {
      action: PlaybackControlAction;
      options?: { speed?: number; position?: string };
    }) => controlPlayback(session?.id as string, action, options),
    onSuccess: (_result, { action }) => {
      toast.info("Command sent", `The ${action.replace("_", " ")} command was sent to the device.`);
    },
    onError: (error: unknown) => {
      const apiError = error instanceof ApiError ? error : null;
      toast.error("Command failed", apiError?.message ?? "The device did not accept the command.");
    },
  });

  async function ensureStopped(sessionId: string): Promise<void> {
    if (stoppedSessionIdsRef.current.has(sessionId)) return;
    stoppedSessionIdsRef.current.add(sessionId);
    try {
      await stopVideoSession(sessionId);
    } catch {
      // Best-effort teardown, mirroring `useVideoSessionController.ensureStopped` exactly - a
      // failed stop must never block the UI from resetting, and the relay's own idle sweep is
      // the backstop.
    }
  }

  // Same per-session cleanup as the live controller: unmount, or a new session replacing this
  // one, tears the old one down server-side so an abandoned playback stops costing the device's
  // uplink (ADR-0044 §6).
  useEffect(() => {
    return () => {
      if (session && !manuallyStopped) {
        void ensureStopped(session.id);
      }
    };
  }, [session, manuallyStopped]);

  // Changing the device/camera abandons any session opened for the previous one.
  useEffect(() => {
    setSession(null);
    setManuallyStopped(false);
    setRequestError(null);
  }, [deviceId, cameraId]);

  const streamUrl = session && !manuallyStopped ? session.streamUrl : null;
  const videoRef = useRef<HTMLVideoElement>(null);
  const player = useMpegtsPlayer(streamUrl, videoRef);

  function computePhase(): VideoSessionPhase {
    if (startMutation.isPending) return "requesting";
    if (requestError) return requestError.unavailable ? "unavailable" : "error";
    if (!session) return "idle";
    if (manuallyStopped) return "stopped";
    if (streamUrl === null) return "unavailable";
    if (player.state === "connected") return player.stalled ? "stalled" : "connected";
    if (player.state === "error") return "error";
    // A playback stream ends on its own when the recording runs out - the relay closes the
    // viewer socket exactly as it does for any other ended session. Reported as "unavailable"
    // rather than inventing a "finished" phase this transport cannot actually distinguish from
    // a relay-side failure.
    if (player.state === "closed") return "unavailable";
    return "connecting";
  }

  const phase = computePhase();
  const canStop = phase === "connecting" || phase === "connected" || phase === "stalled";

  async function stop(): Promise<void> {
    if (!session) return;
    setManuallyStopped(true);
    await ensureStopped(session.id);
    toast.info("Playback stopped", "The playback session has been stopped.");
  }

  function start(windowStart: string, windowEnd: string): void {
    if (deviceId === null || cameraId === null) return;
    // Replaces any open session: the cleanup effect above stops the previous one server-side
    // before this new request's own session takes its place.
    setSession(null);
    startMutation.mutate({ windowStart, windowEnd });
  }

  function control(
    action: PlaybackControlAction,
    options?: { speed?: number; position?: string },
  ): void {
    if (!session) return;
    controlMutation.mutate({ action, options });
  }

  return {
    phase,
    requestError,
    player,
    videoRef,
    session,
    canStop,
    isControlling: controlMutation.isPending,
    start,
    stop,
    control,
  };
}
