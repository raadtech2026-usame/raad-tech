import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Grid2x2, Maximize2, Minimize2, Video, VideoOff, X } from "lucide-react";
import { Badge } from "../../shared/components/Badge/Badge";
import { Button } from "../../shared/components/Button/Button";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import type { VideoCameraOption } from "./api";
import { CameraTile } from "./CameraTile";
import type { VideoSessionPhase } from "./useVideoSessionController";
import styles from "./MultiCameraVideoPanel.module.css";

export interface MultiCameraVideoPanelProps {
  deviceId: string;
  cameras: VideoCameraOption[];
  /** `is_online` best-effort telemetry (ADR-0020/0027) — a visible hint only, never disables
   * Start (ADR-0028 §D): the real authority is each camera's own `POST /video/live` call. */
  deviceOnline: boolean;
}

const LIVE_PHASES = new Set<VideoSessionPhase>(["connected"]);
const PENDING_PHASES = new Set<VideoSessionPhase>(["requesting", "connecting", "idle"]);

/**
 * ADR-0028/0029 evolution, now a CCTV-style video wall (UI-only redesign): one tile per camera
 * the resolved device actually reports, never a hardcoded count. **Not a second video-session
 * architecture**: each `CameraTile` owns its own, completely unmodified `useVideoSessionController`
 * instance, so per-camera start/stop, error isolation, and teardown are exactly the existing
 * single-camera behavior, just run N times in parallel. This component only orchestrates *when*
 * those N instances exist and *how they're laid out* — it never starts a second session for a
 * camera that already has one.
 *
 * - **Start Live** mounts one `CameraTile` per camera; each tile's own effect calls its own
 *   `session.start()` exactly once.
 * - **Stop Live** unmounts every tile at once. `useVideoSessionController` already tears down
 *   its own session on unmount (`ensureStopped`, unchanged) — this panel adds no new stop logic
 *   of its own, so there is nothing here that could leave an orphaned session behind.
 * - Each tile reports its own phase back up (`onPhaseChange`) purely so this panel can render an
 *   aggregate "N/M Live" count and isolate a single camera's failure from the rest.
 *
 * **Focus mode is layout only, never a remount.** All `cameras.length` `<CameraTile>` elements
 * are always rendered as direct children of the *same* `.wall` grid container, in the *same*
 * stable order, keyed by `camera.id` — entering/leaving/changing focus only changes each tile's
 * own `gridArea` (an inline style computed below), never which parent element it lives under and
 * never its position in the `cameras.map(...)` array. This is deliberate: React only preserves a
 * keyed component's identity (and so, here, its live `useVideoSessionController` instance and
 * open WebSocket) across a re-render when that element stays a child of the *same* parent — a
 * naive implementation that moved the focused tile's JSX into a visually-separate "main stage"
 * container while rendering the rest into a different "filmstrip" container would unmount and
 * remount both tiles on every focus change, tearing down and re-requesting real backend sessions
 * for no reason. Grid-area placement avoids that failure mode entirely while still giving the
 * focused tile a large, centered slot and the rest a compact filmstrip.
 */
export function MultiCameraVideoPanel({ deviceId, cameras, deviceOnline }: MultiCameraVideoPanelProps) {
  const [liveRequested, setLiveRequested] = useState(false);
  const [phaseByCamera, setPhaseByCamera] = useState<Record<string, VideoSessionPhase>>({});
  const [focusedCameraId, setFocusedCameraId] = useState<string | null>(null);
  const [isPanelFullscreen, setIsPanelFullscreen] = useState(false);
  const wallRef = useRef<HTMLDivElement>(null);

  // A newly selected vehicle's device never inherits the previous device's "live"/focus state —
  // each outgoing CameraTile's own unmount already stops its session; this only resets this
  // panel's own Start/Stop/layout UI to match the fresh device.
  useEffect(() => {
    setLiveRequested(false);
    setPhaseByCamera({});
    setFocusedCameraId(null);
  }, [deviceId]);

  useEffect(() => {
    function handleFullscreenChange(): void {
      setIsPanelFullscreen(document.fullscreenElement === wallRef.current);
    }
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  const handlePhaseChange = useCallback((cameraId: string, phase: VideoSessionPhase) => {
    setPhaseByCamera((prev) => (prev[cameraId] === phase ? prev : { ...prev, [cameraId]: phase }));
  }, []);

  function handleStart(): void {
    setPhaseByCamera({});
    setFocusedCameraId(null);
    setLiveRequested(true);
  }

  function handleStop(): void {
    setLiveRequested(false);
    setPhaseByCamera({});
    setFocusedCameraId(null);
  }

  function toggleGrid(): void {
    setFocusedCameraId(null);
  }

  function toggleFocus(): void {
    setFocusedCameraId((current) => current ?? cameras[0]?.id ?? null);
  }

  function togglePanelFullscreen(): void {
    if (document.fullscreenElement) {
      void document.exitFullscreen?.();
      return;
    }
    void wallRef.current?.requestFullscreen?.();
  }

  const hasCameras = cameras.length > 0;
  const liveCount = cameras.reduce((n, c) => n + (LIVE_PHASES.has(phaseByCamera[c.id]) ? 1 : 0), 0);
  const pendingCount = cameras.reduce((n, c) => n + (PENDING_PHASES.has(phaseByCamera[c.id]) ? 1 : 0), 0);
  const isFocusMode = focusedCameraId !== null && cameras.length > 1;
  // Compacted thumbnail positions (t0, t1, …) among the *non*-focused cameras only — computed
  // purely for CSS placement, never used to decide what mounts or in what array order below.
  const otherCameraIds = isFocusMode ? cameras.filter((c) => c.id !== focusedCameraId).map((c) => c.id) : [];

  let statusIndicator: ReactNode = null;
  if (liveRequested && hasCameras) {
    if (liveCount > 0) {
      statusIndicator = <LiveIndicator>{`${liveCount}/${cameras.length} Live`}</LiveIndicator>;
    } else if (pendingCount > 0) {
      statusIndicator = (
        <Badge variant="info" dot pulsing>
          Connecting
        </Badge>
      );
    } else {
      statusIndicator = (
        <Badge variant="danger" dot>
          0/{cameras.length} Live
        </Badge>
      );
    }
  }

  return (
    <Card className={styles.card}>
      <CardHeader
        title="Live Video"
        action={
          <div className={styles.headerActions}>
            {statusIndicator}
            {liveRequested ? (
              <Button size="sm" variant="danger" onClick={handleStop}>
                Stop Live
              </Button>
            ) : (
              <Button size="sm" onClick={handleStart} disabled={!hasCameras}>
                Start Live
              </Button>
            )}
          </div>
        }
      />

      {liveRequested && hasCameras && cameras.length > 1 && (
        <div className={styles.toolbar}>
          <span className={styles.toolbarLabel}>Live Cameras</span>
          <span className={styles.audioHint}>Video only</span>
          <div className={styles.toolbarActions}>
            <div className={styles.viewToggle} role="group" aria-label="Video wall layout">
              <button
                type="button"
                className={styles.viewToggleButton}
                data-active={!isFocusMode}
                onClick={toggleGrid}
                aria-pressed={!isFocusMode}
              >
                <Grid2x2 size={14} />
                Grid
              </button>
              <button
                type="button"
                className={styles.viewToggleButton}
                data-active={isFocusMode}
                onClick={toggleFocus}
                aria-pressed={isFocusMode}
              >
                <Video size={14} />
                Focus
              </button>
            </div>
            <button
              type="button"
              className={styles.toolbarIconButton}
              onClick={togglePanelFullscreen}
              aria-label={isPanelFullscreen ? "Exit fullscreen" : "Fullscreen video wall"}
            >
              {isPanelFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
          </div>
        </div>
      )}

      <div className={styles.body}>
        {!hasCameras && (
          <EmptyState icon={<VideoOff size={28} />} title="No camera channels configured" />
        )}

        {hasCameras && !deviceOnline && (
          <Badge variant="warning" className={styles.offlineBadge}>
            Device last reported offline — a live stream may fail.
          </Badge>
        )}

        {hasCameras && !liveRequested && (
          <EmptyState
            icon={<Video size={28} />}
            title={`${cameras.length} camera${cameras.length === 1 ? "" : "s"} ready`}
            description="Press Start Live to view every connected camera on this device."
          />
        )}

        {hasCameras && liveRequested && (
          <div
            ref={wallRef}
            className={styles.wall}
            data-mode={isFocusMode ? "focus" : "grid"}
            data-count={Math.min(cameras.length, 4)}
          >
            {isFocusMode && (
              <button type="button" className={styles.closeFocusButton} onClick={toggleGrid}>
                <X size={14} />
                Back to grid
              </button>
            )}
            {cameras.map((camera) => {
              const isFocused = isFocusMode && camera.id === focusedCameraId;
              const slotStyle = isFocusMode
                ? { gridArea: isFocused ? "main" : `t${otherCameraIds.indexOf(camera.id)}` }
                : undefined;
              return (
                <div
                  key={camera.id}
                  className={isFocusMode ? (isFocused ? styles.mainSlot : styles.thumbSlot) : styles.gridSlot}
                  style={slotStyle}
                >
                  <CameraTile
                    deviceId={deviceId}
                    camera={camera}
                    onPhaseChange={handlePhaseChange}
                    variant={isFocusMode ? (isFocused ? "main" : "thumb") : "grid"}
                    onSelect={cameras.length > 1 ? setFocusedCameraId : undefined}
                    isFocused={isFocused}
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
