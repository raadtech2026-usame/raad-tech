import { useEffect, useRef, useState } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import { Badge, type BadgeVariant } from "../../shared/components/Badge/Badge";
import type { VideoCameraOption } from "./api";
import { VideoPlayerPanel } from "./VideoPlayerPanel";
import { useVideoSessionController, type VideoSessionPhase } from "./useVideoSessionController";
import styles from "./CameraTile.module.css";

export interface CameraTileProps {
  deviceId: string;
  camera: VideoCameraOption;
  /** Reports this tile's own session phase up to the orchestrating grid so it can compute an
   * aggregate "N/M Live" count — each tile owns exactly one `useVideoSessionController` instance
   * (below) and never shares state with its siblings. */
  onPhaseChange?: (cameraId: string, phase: VideoSessionPhase) => void;
}

const PHASE_BADGE: Record<VideoSessionPhase, { label: string; variant: BadgeVariant; pulsing?: boolean }> = {
  idle: { label: "Starting", variant: "neutral" },
  requesting: { label: "Starting", variant: "neutral" },
  connecting: { label: "Connecting", variant: "info", pulsing: true },
  connected: { label: "Live", variant: "success", pulsing: true },
  stopped: { label: "Stopped", variant: "neutral" },
  unavailable: { label: "Unavailable", variant: "warning" },
  error: { label: "Error", variant: "danger" },
};

/**
 * One tile in `MultiCameraVideoPanel`'s grid. Wraps the existing, unchanged
 * `useVideoSessionController` — this is genuinely one independent controller instance per
 * camera, not a new multi-camera session mechanism: starting is a single `start()` call fired
 * once on mount, and stopping is handled entirely by that hook's own existing unmount cleanup
 * (`ensureStopped`) when the parent grid removes this tile — see `MultiCameraVideoPanel`'s own
 * docstring for why that is sufficient for a clean global Stop.
 */
export function CameraTile({ deviceId, camera, onPhaseChange }: CameraTileProps) {
  const session = useVideoSessionController(deviceId, camera.id);
  const startedRef = useRef(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Fires exactly once per tile lifetime — the tile only ever mounts once its device/camera are
  // already known, so `session.canStart` is true on the very first render.
  useEffect(() => {
    if (!startedRef.current && session.canStart) {
      startedRef.current = true;
      session.start();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    onPhaseChange?.(camera.id, session.phase);
  }, [camera.id, session.phase, onPhaseChange]);

  useEffect(() => {
    function handleFullscreenChange(): void {
      setIsFullscreen(document.fullscreenElement === wrapRef.current);
    }
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  function toggleFullscreen(): void {
    if (document.fullscreenElement) {
      void document.exitFullscreen?.();
      return;
    }
    // Not supported in every test/embedded environment — a no-op `?.()` is the honest behavior
    // rather than throwing, since this control is a convenience, not core functionality.
    void wrapRef.current?.requestFullscreen?.();
  }

  const label = camera.label ?? `Camera ${camera.channelNo}`;
  const badge = PHASE_BADGE[session.phase];

  return (
    <div className={styles.tile} ref={wrapRef} data-phase={session.phase}>
      <div className={styles.tileHeader}>
        <Badge variant={badge.variant} dot pulsing={badge.pulsing}>
          {badge.label}
        </Badge>
        <span className={styles.channel}>Channel {camera.channelNo}</span>
      </div>

      <div className={styles.videoArea}>
        <VideoPlayerPanel
          phase={session.phase}
          requestError={session.requestError}
          player={session.player}
          videoRef={session.videoRef}
          idleTitle="Starting…"
          idleDescription=""
        />
      </div>

      <div className={styles.tileFooter}>
        <span className={styles.name}>{label}</span>
        <button
          type="button"
          className={styles.fullscreenButton}
          onClick={toggleFullscreen}
          aria-label={isFullscreen ? `Exit fullscreen for ${label}` : `Fullscreen ${label}`}
        >
          {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
      </div>
    </div>
  );
}
