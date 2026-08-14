import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Video, VideoOff } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { FormField } from "../../shared/components/FormField/FormField";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { Button } from "../../shared/components/Button/Button";
import { useToast } from "../../shared/components/Toast/toastStore";
import { ApiError } from "../../shared/api/types";
import {
  listDevicesForVideoPicker,
  requestLiveVideo,
  stopVideoSession,
  type VideoSession,
} from "./api";
import { useRelayStreamSocket } from "./useRelayStreamSocket";
import styles from "./VideoPage.module.css";

/**
 * `/org/video` (F10 — Organization Admin Web Live Video). Reuses the existing `POST /video/live`
 * / `POST /video/sessions/{id}/stop` contracts and the entire ADR-0024/0025/0026 authorization
 * chain unchanged (`enforce_d5` still runs server-side before any session is created; this page
 * never makes an authorization decision of its own — `.claude/rules/security.md` #5's "video is
 * Org-Admin-only by... construction" holds exactly as before). **Org Admin only** — this is not
 * the Parent mobile video capability (`mobile/lib/features/video/`, ADR-0026 §5); no per-parent
 * grant UI, no playback-window picker, nothing Parent-specific appears here.
 *
 * **Device-first picker, not vehicle-first — a real, confirmed contract gap, not a design
 * preference.** `fleet_device.api.schemas.DeviceResponse` carries no `vehicle_id`, and no `GET`
 * route anywhere resolves "which device is on vehicle X" (`api.ts`'s own `VideoDeviceOption`
 * docstring has the full citation). `POST /video/live` itself takes `device_id`/`camera_id`
 * directly, never `vehicle_id`, so a device picker is both the honest and the sufficient shape —
 * inventing a fake vehicle-to-device join client-side would misrepresent data this platform
 * genuinely cannot correlate today.
 *
 * **No browser video rendering — flagged, not faked.** `stream_url` points at the JT1078 relay's
 * own WS-FLV viewer endpoint: a raw WebSocket carrying hand-rolled binary FLV bytes
 * (`services/jt1078/src/viewer/`), not HTTP-FLV, not HLS, not MSE-ready fMP4. No browser can
 * play that without an FLV-over-WebSocket demuxer/remuxer (e.g. `flv.js`) — not an approved
 * dependency in this codebase (`.claude/rules/workflow.md` #1/#2), and hand-rolling one here would
 * mean re-implementing a production media library inside a single page component, an explicit
 * anti-pattern this change was told to avoid ("do not invent a replacement transport"). This page
 * therefore implements the *entire* real, authorized session lifecycle (device/camera selection,
 * request, relay-connectivity proof via `useRelayStreamSocket`, stop, cleanup) and is honest in
 * the `"connected"` state that pixel playback itself isn't wired yet, rather than faking a player
 * or silently omitting the capability.
 */
export function VideoPage() {
  usePageHeader("Live Video", "Request and view an authorized live camera stream");
  const toast = useToast();

  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [selectedCameraId, setSelectedCameraId] = useState("");
  const [session, setSession] = useState<VideoSession | null>(null);
  const [manuallyStopped, setManuallyStopped] = useState(false);
  const [requestError, setRequestError] = useState<{ message: string; unavailable: boolean } | null>(
    null,
  );
  const stoppedSessionIdsRef = useRef<Set<string>>(new Set());

  const devicesQuery = useQuery({
    queryKey: ["devices", "video-picker"],
    queryFn: () => listDevicesForVideoPicker(""),
    staleTime: 60_000,
  });

  const selectedDevice = devicesQuery.data?.find((d) => d.id === selectedDeviceId) ?? null;

  const startMutation = useMutation({
    mutationFn: () => requestLiveVideo(selectedDeviceId, selectedCameraId),
    onSuccess: (newSession) => {
      setSession(newSession);
      setManuallyStopped(false);
      setRequestError(null);
    },
    onError: (error: unknown) => {
      const apiError = error instanceof ApiError ? error : null;
      setRequestError({
        message: apiError?.message ?? "Could not start the video session.",
        // A missing `VideoProviderPort` on this deployment and a genuine unexpected error are
        // indistinguishable at the HTTP layer (both a 500 `INTERNAL_ERROR`,
        // `video/api/routers.py`'s own documented behavior) — treated as "unavailable," not
        // claimed as certainly one or the other.
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
  }, [selectedDeviceId, selectedCameraId]);

  const streamUrl = session && !manuallyStopped ? session.streamUrl : null;
  const relay = useRelayStreamSocket(streamUrl);

  async function handleStop(): Promise<void> {
    if (!session) return;
    setManuallyStopped(true);
    await ensureStopped(session.id);
    toast.info("Session stopped", "The live video session has been stopped.");
  }

  function handleStart(): void {
    startMutation.mutate();
  }

  type ViewerPhase =
    | "idle"
    | "requesting"
    | "connecting"
    | "connected"
    | "stopped"
    | "unavailable"
    | "error";

  function computePhase(): ViewerPhase {
    if (startMutation.isPending) return "requesting";
    if (requestError) return requestError.unavailable ? "unavailable" : "error";
    if (!session) return "idle";
    if (manuallyStopped) return "stopped";
    if (relay.state === "connected") return "connected";
    if (relay.state === "closed") {
      if (relay.closeCode === 4004) return "unavailable";
      if (relay.closeCode === 4001) return "error";
      return "stopped";
    }
    if (relay.state === "error") return "error";
    return "connecting";
  }

  const phase = computePhase();
  const canStart =
    selectedDeviceId !== "" &&
    selectedCameraId !== "" &&
    phase !== "requesting" &&
    phase !== "connecting" &&
    phase !== "connected";
  const canStop = phase === "connecting" || phase === "connected";

  return (
    <div className={styles.page}>
      <Card padded className={styles.sidebar}>
        <FormField label="Device">
          {devicesQuery.isLoading ? (
            <Skeleton height={36} />
          ) : (
            <Select
              value={selectedDeviceId}
              onChange={(e) => {
                setSelectedDeviceId(e.target.value);
                setSelectedCameraId("");
              }}
              aria-label="Device"
            >
              <option value="">Select a device</option>
              {(devicesQuery.data ?? []).map((device) => (
                <option key={device.id} value={device.id}>
                  {device.terminalId}
                  {device.vendor || device.model
                    ? ` — ${[device.vendor, device.model].filter(Boolean).join(" ")}`
                    : ""}
                </option>
              ))}
            </Select>
          )}
        </FormField>

        <FormField label="Camera">
          <Select
            value={selectedCameraId}
            onChange={(e) => setSelectedCameraId(e.target.value)}
            aria-label="Camera"
            disabled={!selectedDevice}
          >
            <option value="">Select a camera</option>
            {(selectedDevice?.cameras ?? []).map((camera) => (
              <option key={camera.id} value={camera.id}>
                {camera.label ?? `Channel ${camera.channelNo}`} ({camera.position})
              </option>
            ))}
          </Select>
        </FormField>

        <div className={styles.actions}>
          <Button onClick={handleStart} disabled={!canStart} loading={phase === "requesting"} fullWidth>
            Start Live
          </Button>
          <Button onClick={handleStop} disabled={!canStop} variant="danger" fullWidth>
            Stop
          </Button>
        </div>
      </Card>

      <Card className={styles.playerCard}>
        <CardHeader
          title="Live Stream"
          action={
            phase === "connected" || phase === "connecting" ? (
              <LiveIndicator>{phase === "connected" ? "Live" : "Connecting"}</LiveIndicator>
            ) : undefined
          }
        />
        <div className={styles.playerArea}>
          {phase === "idle" && (
            <EmptyState
              icon={<Video size={28} />}
              title="Select a device and camera"
              description="Choose a device and one of its cameras, then press Start Live."
            />
          )}
          {phase === "requesting" && (
            <EmptyState icon={<Loader2 size={28} className={styles.spin} />} title="Requesting a live session…" />
          )}
          {phase === "connecting" && (
            <EmptyState icon={<Loader2 size={28} className={styles.spin} />} title="Connecting to the relay…" />
          )}
          {phase === "connected" && (
            <EmptyState
              icon={<Video size={28} />}
              title="Stream is live on the relay"
              description={
                `${formatBytes(relay.bytesReceived)} received — browser playback isn't wired yet ` +
                "for this transport (WS-FLV needs an additional media library, not yet approved). " +
                "The session is real and authorized; only in-page rendering is missing."
              }
            />
          )}
          {phase === "stopped" && (
            <EmptyState icon={<VideoOff size={28} />} title="Session stopped" description="Press Start Live to request a new session." />
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
              description={requestError?.message ?? "The connection to the video relay failed."}
            />
          )}
        </div>
      </Card>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
