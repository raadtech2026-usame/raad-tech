import type { RefObject } from "react";
import { AlertTriangle, Loader2, Video, VideoOff } from "lucide-react";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import type { UseMpegtsPlayerResult } from "./useMpegtsPlayer";
import type { VideoRequestError, VideoSessionPhase } from "./useVideoSessionController";
import styles from "./VideoPlayerPanel.module.css";

export interface VideoPlayerPanelProps {
  phase: VideoSessionPhase;
  requestError: VideoRequestError | null;
  player: UseMpegtsPlayerResult;
  videoRef: RefObject<HTMLVideoElement>;
  /** Copy for the `idle` empty state — default to `VideoPage`'s original device-first wording
   * (its own tests assert this exact title); the unified Vehicle Operations view overrides both
   * since it has no device-picker step of its own (the device is already resolved by the time
   * this panel renders). */
  idleTitle?: string;
  idleDescription?: string;
  /** Defaults to `true` (unchanged behavior — `VideoPage.tsx`'s single large player has room for
   * this). `CameraTile` (video-wall redesign) passes `false`: repeating this notice on every
   * compact wall tile collided with the tile's own bottom name/controls bar (a real, observed
   * text-overlap bug) — the wall now surfaces this fact once, in the panel toolbar, instead. */
  showAudioNotice?: boolean;
}

/**
 * ADR-0028 §G: the phase-driven player/overlay block extracted from `VideoPage`, reused
 * unchanged by both the standalone device-first page and the unified Vehicle Operations view.
 * Purely presentational — every phase transition is decided by `useVideoSessionController`, not
 * here.
 */
export function VideoPlayerPanel({
  phase,
  requestError,
  player,
  videoRef,
  idleTitle = "Select a device and camera",
  idleDescription = "Choose a device and one of its cameras, then press Start Live.",
  showAudioNotice = true,
}: VideoPlayerPanelProps) {
  return (
    <>
      {/* Mounted for the entire connecting/connected span so `videoRef.current` is already
          set by the time `useMpegtsPlayer`'s effect runs — never conditionally rendered only
          on `"connected"`, or the player would have no element to attach to. Audio is
          deliberately excluded (see `useMpegtsPlayer`'s own module docstring), so `muted` is
          set unconditionally rather than depending on autoplay-gesture propagation. */}
      {(phase === "connecting" || phase === "connected") && (
        <div className={styles.videoWrap}>
          <video ref={videoRef} className={styles.video} muted playsInline data-testid="live-video" />
          {phase === "connecting" && (
            <div className={styles.videoOverlay}>
              <Loader2 size={28} className={styles.spin} />
              <span>Connecting to the relay…</span>
            </div>
          )}
          {phase === "connected" && showAudioNotice && (
            <span className={styles.audioNotice}>Video only — audio isn't available on this stream yet.</span>
          )}
        </div>
      )}
      {phase === "idle" && (
        <EmptyState icon={<Video size={28} />} title={idleTitle} description={idleDescription} />
      )}
      {phase === "requesting" && (
        <EmptyState icon={<Loader2 size={28} className={styles.spin} />} title="Requesting a live session…" />
      )}
      {phase === "stopped" && (
        <EmptyState
          icon={<VideoOff size={28} />}
          title="Session stopped"
          description="Press Start Live to request a new session."
        />
      )}
      {phase === "unavailable" && (
        <EmptyState
          icon={<VideoOff size={28} />}
          title="Video is unavailable"
          description="This deployment's video relay isn't reachable right now, or the requested camera has no active session. Try again shortly."
        />
      )}
      {phase === "error" && (
        <EmptyState
          icon={<AlertTriangle size={28} />}
          title="Something went wrong"
          description={requestError?.message ?? player.errorMessage ?? "The connection to the video relay failed."}
        />
      )}
    </>
  );
}
