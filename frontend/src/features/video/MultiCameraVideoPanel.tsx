import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Video, VideoOff } from "lucide-react";
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
 * ADR-0028/0029 evolution: replaces the single-camera `CameraPicker` + one `VideoPlayerPanel`
 * with a data-driven grid — one tile per camera the resolved device actually reports, never a
 * hardcoded count. **Not a second video-session architecture**: each `CameraTile` owns its own,
 * completely unmodified `useVideoSessionController` instance, so per-camera start/stop, error
 * isolation, and teardown are exactly the existing single-camera behavior, just run N times in
 * parallel. This component only orchestrates *when* those N instances exist:
 *
 * - **Start Live** mounts one `CameraTile` per camera; each tile's own effect calls its own
 *   `session.start()` exactly once.
 * - **Stop Live** unmounts every tile at once. `useVideoSessionController` already tears down
 *   its own session on unmount (`ensureStopped`, unchanged) — this panel adds no new stop logic
 *   of its own, so there is nothing here that could leave an orphaned session behind.
 * - Each tile reports its own phase back up (`onPhaseChange`) purely so this panel can render an
 *   aggregate "N/M Live" count and isolate a single camera's failure from the rest, per the
 *   real-world "camera 3 errors, cameras 1/2/4 stay live" requirement.
 */
export function MultiCameraVideoPanel({ deviceId, cameras, deviceOnline }: MultiCameraVideoPanelProps) {
  const [liveRequested, setLiveRequested] = useState(false);
  const [phaseByCamera, setPhaseByCamera] = useState<Record<string, VideoSessionPhase>>({});

  // A newly selected vehicle's device never inherits the previous device's "live" state — each
  // outgoing CameraTile's own unmount already stops its session; this only resets this panel's
  // own Start/Stop UI to match the fresh device.
  useEffect(() => {
    setLiveRequested(false);
    setPhaseByCamera({});
  }, [deviceId]);

  const handlePhaseChange = useCallback((cameraId: string, phase: VideoSessionPhase) => {
    setPhaseByCamera((prev) => (prev[cameraId] === phase ? prev : { ...prev, [cameraId]: phase }));
  }, []);

  function handleStart(): void {
    setPhaseByCamera({});
    setLiveRequested(true);
  }

  function handleStop(): void {
    setLiveRequested(false);
    setPhaseByCamera({});
  }

  const hasCameras = cameras.length > 0;
  const liveCount = cameras.reduce((n, c) => n + (LIVE_PHASES.has(phaseByCamera[c.id]) ? 1 : 0), 0);
  const pendingCount = cameras.reduce((n, c) => n + (PENDING_PHASES.has(phaseByCamera[c.id]) ? 1 : 0), 0);

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
          <div className={styles.grid}>
            {cameras.map((camera) => (
              <CameraTile key={camera.id} deviceId={deviceId} camera={camera} onPhaseChange={handlePhaseChange} />
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
