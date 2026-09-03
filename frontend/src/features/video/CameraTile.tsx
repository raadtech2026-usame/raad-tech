import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Maximize2, Minimize2, Pause, Play } from "lucide-react";
import clsx from "clsx";
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
  /** UI-only presentation size (video-wall redesign) — never affects the underlying session:
   * `"grid"` (default) is an ordinary wall tile, `"main"` is the large focused tile in Focus
   * mode, `"thumb"` is a filmstrip thumbnail alongside it. Purely a styling/detail-density hint;
   * `CameraTile` still owns exactly one `useVideoSessionController` instance regardless. */
  variant?: "grid" | "main" | "thumb";
  /** Present only when this tile is one of several selectable tiles (`MultiCameraVideoPanel`
   * omits it entirely for a single-camera device) — clicking the tile (outside its own
   * fullscreen button) calls this with the camera's id to enter/change Focus mode. Purely a
   * frontend presentation switch; it never starts, stops, or re-requests a video session. */
  onSelect?: (cameraId: string) => void;
  /** Whether this tile is the currently focused one (Focus mode's main tile) — a styling hint
   * only (highlighted border, `aria-pressed`), computed and owned entirely by the parent grid. */
  isFocused?: boolean;
}

const PHASE_BADGE: Record<VideoSessionPhase, { label: string; variant: BadgeVariant; pulsing?: boolean }> = {
  idle: { label: "Starting", variant: "neutral" },
  requesting: { label: "Starting", variant: "neutral" },
  connecting: { label: "Connecting", variant: "info", pulsing: true },
  connected: { label: "Live", variant: "success", pulsing: true },
  // Not "Live": the socket is open and a frame decoded, but the picture has stopped advancing.
  // Never pulsing - a pulsing badge reads as "flowing", which is exactly the false confidence
  // this phase exists to correct.
  stalled: { label: "No signal", variant: "warning" },
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
export function CameraTile({
  deviceId,
  camera,
  onPhaseChange,
  variant = "grid",
  onSelect,
  isFocused,
}: CameraTileProps) {
  const session = useVideoSessionController(deviceId, camera.id);
  const startedRef = useRef(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isPaused, setIsPaused] = useState(false);

  // Fires exactly once per tile lifetime — the tile only ever mounts once its device/camera are
  // already known, so `session.canStart` is true on the very first render.
  //
  // The actual `session.start()` call is deferred by one macrotask, not called synchronously in
  // the effect body — required for correctness under React 18 StrictMode (dev only), not a
  // stylistic choice. StrictMode mounts every component twice: run this effect, synchronously
  // simulate an unmount (run cleanup), then run it again. `useVideoSessionController`'s own
  // `useMutation` subscribes to its result via an internal effect that gets torn down and
  // recreated across that exact same synchronous double-invoke — a `mutate()` call issued
  // synchronously during the first (soon-to-be-torn-down) pass resolves against a subscription
  // that's already gone by the time the response arrives, so `isPending` never flips back to
  // `false` and `onSuccess` never fires: the tile is stuck on "Requesting a live session…"
  // forever, `<video>` never mounts, and `useMpegtsPlayer` never gets a real element to attach
  // to — confirmed live (2026-08-22): `POST /video/live` genuinely succeeds server-side every
  // time, but the browser never even attempts `new WebSocket(streamUrl)`. Deferring the call
  // with `setTimeout(0)` lets StrictMode's synchronous mount/cleanup/remount dance finish first,
  // so `mutate()` only ever runs against the subscription that's actually still live — the
  // `startedRef` check moves inside the timeout for the same reason (the first pass's timeout is
  // cancelled by cleanup before it fires; only the surviving second pass's callback runs).
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (!startedRef.current && session.canStart) {
        startedRef.current = true;
        session.start();
      }
    }, 0);
    return () => clearTimeout(timeoutId);
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

  function toggleFullscreen(event: MouseEvent): void {
    event.stopPropagation();
    if (document.fullscreenElement) {
      void document.exitFullscreen?.();
      return;
    }
    // Not supported in every test/embedded environment — a no-op `?.()` is the honest behavior
    // rather than throwing, since this control is a convenience, not core functionality.
    void wrapRef.current?.requestFullscreen?.();
  }

  // Pure frontend presentation control, operating directly on the native `<video>` element this
  // tile's own `useVideoSessionController` already exposes via `session.videoRef` — every
  // `HTMLMediaElement` supports `pause()`/`play()` regardless of the MSE/mpegts.js machinery
  // feeding it, so this genuinely "pauses/freezes the current frontend player" (freezing on the
  // last decoded frame while the underlying WebSocket keeps receiving) without sending any new
  // backend/relay command and without touching `useVideoSessionController`/`useMpegtsPlayer` at
  // all. Only shown once `phase === "connected"` — there is nothing real to pause before then.
  function togglePause(event: MouseEvent): void {
    event.stopPropagation();
    const video = session.videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play().catch(() => {});
      setIsPaused(false);
    } else {
      video.pause();
      setIsPaused(true);
    }
  }

  function handleSelect(): void {
    onSelect?.(camera.id);
  }

  function handleKeyDown(event: KeyboardEvent): void {
    if (!onSelect) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleSelect();
    }
  }

  const label = camera.label ?? `Camera ${camera.channelNo}`;
  const badge = PHASE_BADGE[session.phase];
  const selectable = onSelect !== undefined;
  // Only render a second, distinct name span when there's genuinely a custom label to show —
  // the fallback `Camera N` string would otherwise sit directly beside `Channel N`, repeating
  // the same number twice for no reason (the exact "duplicated channel label" this consolidated
  // top-right group replaces the old split header/footer placement for).
  const hasCustomLabel = Boolean(camera.label);

  return (
    <div
      className={clsx(styles.tile, styles[`variant-${variant}`], selectable && styles.selectable, isFocused && styles.focused)}
      ref={wrapRef}
      data-phase={session.phase}
      data-variant={variant}
      onClick={selectable ? handleSelect : undefined}
      onKeyDown={selectable ? handleKeyDown : undefined}
      role={selectable ? "button" : undefined}
      tabIndex={selectable ? 0 : undefined}
      aria-pressed={selectable ? Boolean(isFocused) : undefined}
      aria-label={selectable ? `View ${label} in focus mode` : undefined}
    >
      <div className={styles.tileHeader}>
        <Badge variant={badge.variant} dot pulsing={badge.pulsing} className={styles.liveBadge}>
          {badge.label}
        </Badge>
        {/* The one clean channel label for this tile — channel number always, the operator's
            own custom camera name only when one is actually set. */}
        <div className={styles.channelLabel}>
          <span className={styles.channel}>Channel {camera.channelNo}</span>
          {hasCustomLabel && <span className={styles.name}>{label}</span>}
        </div>
      </div>

      <div className={styles.videoArea}>
        <VideoPlayerPanel
          phase={session.phase}
          requestError={session.requestError}
          player={session.player}
          videoRef={session.videoRef}
          idleTitle="Starting…"
          idleDescription=""
          showAudioNotice={false}
        />
        {isPaused && session.phase === "connected" && (
          <div className={styles.pausedOverlay} aria-hidden="true">
            <Pause size={28} />
          </div>
        )}
      </div>

      {/* Controls-only overlay, bottom-right — hidden until hover/keyboard-focus (a clean idle
          tile shows only the live badge and channel label), never anything else at the bottom
          that could compete with the video image itself. */}
      <div className={styles.tileControls}>
        {session.phase === "connected" && variant !== "thumb" && (
          <button
            type="button"
            className={styles.controlButton}
            onClick={togglePause}
            aria-label={isPaused ? `Resume ${label}` : `Pause ${label}`}
          >
            {isPaused ? <Play size={14} /> : <Pause size={14} />}
          </button>
        )}
        <button
          type="button"
          className={styles.controlButton}
          onClick={toggleFullscreen}
          aria-label={isFullscreen ? `Exit fullscreen for ${label}` : `Fullscreen ${label}`}
        >
          {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
      </div>
    </div>
  );
}
