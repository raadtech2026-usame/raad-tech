import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { FormField } from "../../shared/components/FormField/FormField";
import { LiveIndicator } from "../../shared/components/LiveIndicator/LiveIndicator";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { Button } from "../../shared/components/Button/Button";
import { CameraPicker } from "./CameraPicker";
import { VideoPlayerPanel } from "./VideoPlayerPanel";
import { useVideoSessionController } from "./useVideoSessionController";
import { listDevicesForVideoPicker } from "./api";
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
 * route resolved "which device is on vehicle X" at the time this page was first built
 * (`api.ts`'s own `VideoDeviceOption` docstring has the full citation). That gap is closed now
 * (ADR-0027, `GET /vehicles/{id}/device-assignment`), but this page is kept exactly as it was —
 * ADR-0028 §B keeps `/org/video` unchanged, since it remains the only reachable path for a
 * device that isn't yet assigned to any vehicle (onboarding, bench-testing). The vehicle-first
 * experience lives instead in `features/live-monitoring/LiveTrackingPage.tsx`, which reuses this
 * feature's own `CameraPicker`/`VideoPlayerPanel`/`useVideoSessionController` (ADR-0028 §G) —
 * this page's session-lifecycle/player logic is unchanged in behavior by that reuse.
 *
 * **Browser playback (`.claude/rules/workflow.md` #1/#2 approved dependency: `mpegts.js@^1.8.2`).**
 * `stream_url` points at the JT1078 relay's own WS-FLV viewer endpoint
 * (`services/jt1078/src/viewer/`) — `useMpegtsPlayer` (via `useVideoSessionController`) attaches
 * `mpegts.js`'s native `WebSocketLoader` directly to it. **Video only, deliberately**: the
 * relay's `flv_muxer.py` has no AAC sequence-header path yet, so audio is explicitly excluded
 * (`hasAudio: false`) — see `useMpegtsPlayer`'s own docstring.
 */
export function VideoPage() {
  usePageHeader("Live Video", "Request and view an authorized live camera stream");

  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [selectedCameraId, setSelectedCameraId] = useState("");

  const devicesQuery = useQuery({
    queryKey: ["devices", "video-picker"],
    queryFn: () => listDevicesForVideoPicker(""),
    staleTime: 60_000,
  });

  const selectedDevice = devicesQuery.data?.find((d) => d.id === selectedDeviceId) ?? null;

  const session = useVideoSessionController(selectedDeviceId || null, selectedCameraId || null);

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

        <CameraPicker
          cameras={selectedDevice?.cameras ?? []}
          value={selectedCameraId}
          onChange={setSelectedCameraId}
          disabled={!selectedDevice}
        />

        <div className={styles.actions}>
          <Button
            onClick={session.start}
            disabled={!session.canStart}
            loading={session.phase === "requesting"}
            fullWidth
          >
            Start Live
          </Button>
          <Button onClick={session.stop} disabled={!session.canStop} variant="danger" fullWidth>
            Stop
          </Button>
        </div>
      </Card>

      <Card className={styles.playerCard}>
        <CardHeader
          title="Live Stream"
          action={
            session.phase === "connected" || session.phase === "connecting" ? (
              <LiveIndicator>{session.phase === "connected" ? "Live" : "Connecting"}</LiveIndicator>
            ) : undefined
          }
        />
        <div className={styles.playerArea}>
          <VideoPlayerPanel
            phase={session.phase}
            requestError={session.requestError}
            player={session.player}
            videoRef={session.videoRef}
          />
        </div>
      </Card>
    </div>
  );
}
