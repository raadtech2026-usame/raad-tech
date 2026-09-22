import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FileVideo } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { FormField } from "../../shared/components/FormField/FormField";
import { Input } from "../../shared/components/Input/Input";
import { Select } from "../../shared/components/Select/Select";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { Button } from "../../shared/components/Button/Button";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { CameraPicker } from "./CameraPicker";
import { VideoPlayerPanel } from "./VideoPlayerPanel";
import { usePlaybackSessionController } from "./usePlaybackSessionController";
import {
  getRecordingSearch,
  listDevicesForVideoPicker,
  searchRecordings,
  type RecordingSegment,
} from "./api";
import styles from "./RecordingsPage.module.css";

/**
 * `/org/recordings` (ADR-0044) — search an MDVR's own stored recordings and play one back.
 *
 * **RAAD never holds the video.** The device is the recording store; this page asks it what it
 * has (`0x9205`, via `POST /video/recordings/search`) and then asks it to replay a chosen
 * segment (`0x9201`, via `POST /video/playback`), which reaches the browser through the same
 * JT1078 relay a live stream does. There is no download, no export and no server-side copy —
 * deliberately, per that ADR's first decision.
 *
 * **The search is asynchronous because the device is.** The terminal answers over the cellular
 * link in its own time, so the search returns a `pending` id immediately and this page polls for
 * the answer up to `MAX_POLL_ATTEMPTS`. A device that never answers is reported as exactly that
 * — never as "no recordings", which is a different and materially misleading claim.
 *
 * **Transport controls send commands; they do not assert state.** Whether a terminal honors
 * pause/seek/fast-forward is firmware-dependent (ADR-0044 Consequences) and its answer travels
 * the device plane, not this HTTP response — so the buttons are stateless and the page says so,
 * rather than rendering an optimistic "Paused" that may be a lie.
 *
 * Authorization is server-side and unchanged: D5 runs before any search or session is created,
 * and every route here reuses `video.playback.start` (ADR-0044 §5) — this page makes no
 * authorization decision of its own (`.claude/rules/frontend.md` #2).
 */

/** The device answers over a cellular link; 2s × 15 ≈ 30s is a generous ceiling for a
 * round trip that normally takes a second or two. Past it the page stops polling and says the
 * device has not answered — the search stays valid server-side for 15 minutes either way. */
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 15;

/** `datetime-local` gives a local wall-clock string with no zone; the API takes ISO-8601. The
 * `Date` constructor interprets it in the browser's own zone, which is what the operator meant. */
function toIsoOrNull(localValue: string): string | null {
  if (!localValue) return null;
  const parsed = new Date(localValue);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

/** `datetime-local` wants `YYYY-MM-DDTHH:mm` in local time — `toISOString` would shift it. */
function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

function formatClock(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString();
}

function formatDuration(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const totalMinutes = Math.round(ms / 60_000);
  if (totalMinutes < 60) return `${totalMinutes} min`;
  return `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m`;
}

/** The device's own figure for the file, shown so an operator can judge a segment. Nothing is
 * transferred — this is not a download size. */
function formatSize(bytes: number): string {
  if (bytes <= 0) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

export function RecordingsPage() {
  usePageHeader("Recordings", "Search and play back video stored on a bus recorder");

  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [selectedCameraId, setSelectedCameraId] = useState("");
  const defaultWindow = useMemo(() => {
    const now = new Date();
    const hourAgo = new Date(now.getTime() - 60 * 60 * 1000);
    return { start: toLocalInputValue(hourAgo), end: toLocalInputValue(now) };
  }, []);
  const [windowStart, setWindowStart] = useState(defaultWindow.start);
  const [windowEnd, setWindowEnd] = useState(defaultWindow.end);
  const [searchId, setSearchId] = useState<string | null>(null);
  const [pollAttempts, setPollAttempts] = useState(0);
  const [playingSegment, setPlayingSegment] = useState<RecordingSegment | null>(null);
  const [speed, setSpeed] = useState(2);

  const devicesQuery = useQuery({
    queryKey: ["devices", "video-picker"],
    queryFn: () => listDevicesForVideoPicker(""),
    staleTime: 60_000,
  });

  const selectedDevice = devicesQuery.data?.find((d) => d.id === selectedDeviceId) ?? null;
  const playback = usePlaybackSessionController(
    selectedDeviceId || null,
    selectedCameraId || null,
  );

  const startIso = toIsoOrNull(windowStart);
  const endIso = toIsoOrNull(windowEnd);
  const windowValid = startIso !== null && endIso !== null && startIso < endIso;

  const searchMutation = useMutation({
    mutationFn: () =>
      searchRecordings(selectedDeviceId, selectedCameraId, startIso as string, endIso as string),
    onSuccess: (search) => {
      setPollAttempts(0);
      setPlayingSegment(null);
      setSearchId(search.searchId);
    },
  });

  const searchQuery = useQuery({
    queryKey: ["video", "recording-search", searchId],
    queryFn: async () => {
      setPollAttempts((attempts) => attempts + 1);
      return getRecordingSearch(searchId as string);
    },
    enabled: searchId !== null,
    // Stops polling as soon as the device answers, and again once the ceiling is reached, so a
    // silent device can never leave this page polling forever.
    refetchInterval: (query) =>
      query.state.data?.status === "ready" || pollAttempts >= MAX_POLL_ATTEMPTS
        ? false
        : POLL_INTERVAL_MS,
  });

  const search = searchQuery.data ?? null;
  const segments = search?.segments ?? null;
  const awaitingDevice = searchId !== null && segments === null;
  const deviceNeverAnswered = awaitingDevice && pollAttempts >= MAX_POLL_ATTEMPTS;

  function playSegment(segment: RecordingSegment): void {
    setPlayingSegment(segment);
    playback.start(segment.startTime, segment.endTime);
  }

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
                setSearchId(null);
                setPlayingSegment(null);
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
          onChange={(cameraId) => {
            setSelectedCameraId(cameraId);
            setSearchId(null);
            setPlayingSegment(null);
          }}
          disabled={!selectedDevice}
        />

        <div className={styles.window}>
          <FormField label="From">
            <Input
              type="datetime-local"
              value={windowStart}
              onChange={(e) => setWindowStart(e.target.value)}
              aria-label="From"
            />
          </FormField>
          <FormField label="To">
            <Input
              type="datetime-local"
              value={windowEnd}
              onChange={(e) => setWindowEnd(e.target.value)}
              aria-label="To"
            />
          </FormField>
        </div>

        <div className={styles.actions}>
          <Button
            onClick={() => searchMutation.mutate()}
            disabled={!selectedCameraId || !windowValid || searchMutation.isPending}
            loading={searchMutation.isPending}
            fullWidth
          >
            Search recordings
          </Button>
          {!windowValid && (
            <span className={styles.segmentMeta}>The "From" time must be before "To".</span>
          )}
          {searchMutation.isError && (
            <span role="alert" className={styles.segmentMeta}>
              Could not ask the device for its recordings.
            </span>
          )}
        </div>

        {searchId !== null && (
          <div className={styles.results}>
            <span className={styles.resultsTitle}>Recordings on the device</span>
            {awaitingDevice && !deviceNeverAnswered && (
              <span className={styles.segmentMeta}>Waiting for the device to answer…</span>
            )}
            {deviceNeverAnswered && (
              <span role="alert" className={styles.segmentMeta}>
                The device did not answer. It may be offline or busy — try again in a moment.
              </span>
            )}
            {segments !== null && segments.length === 0 && (
              <span className={styles.segmentMeta}>
                The device reports no recordings in this window.
              </span>
            )}
            {segments !== null && segments.length > 0 && (
              <ul className={styles.segmentList}>
                {segments.map((segment) => {
                  const key = `${segment.channelNo}-${segment.startTime}-${segment.endTime}`;
                  const isPlaying =
                    playingSegment !== null &&
                    playingSegment.startTime === segment.startTime &&
                    playingSegment.endTime === segment.endTime &&
                    playingSegment.channelNo === segment.channelNo;
                  return (
                    <li key={key}>
                      <button
                        type="button"
                        className={styles.segment}
                        aria-current={isPlaying}
                        onClick={() => playSegment(segment)}
                      >
                        <span className={styles.segmentTime}>
                          {formatClock(segment.startTime)}
                        </span>
                        <span className={styles.segmentMeta}>
                          {[
                            `Channel ${segment.channelNo}`,
                            formatDuration(segment.startTime, segment.endTime),
                            formatSize(segment.sizeBytes),
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </Card>

      <Card className={styles.playerCard}>
        <CardHeader
          title="Playback"
          action={
            playback.canStop ? (
              <Button onClick={() => void playback.stop()} variant="danger" size="sm">
                Stop
              </Button>
            ) : undefined
          }
        />
        <div className={styles.playerArea}>
          {playingSegment === null ? (
            <EmptyState
              icon={<FileVideo size={24} />}
              title="No recording selected"
              description="Search a device's recordings, then choose a segment to play it back from the recorder."
            />
          ) : (
            <VideoPlayerPanel
              phase={playback.phase}
              requestError={playback.requestError}
              player={playback.player}
              videoRef={playback.videoRef}
            />
          )}
        </div>
        {playingSegment !== null && (
          <div className={styles.transport}>
            <Button
              size="sm"
              variant="secondary"
              disabled={!playback.session || playback.isControlling}
              onClick={() => playback.control("pause")}
            >
              Pause
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={!playback.session || playback.isControlling}
              onClick={() => playback.control("resume")}
            >
              Resume
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={!playback.session || playback.isControlling}
              onClick={() => playback.control("fast_forward", { speed })}
            >
              Fast forward
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={!playback.session || playback.isControlling}
              onClick={() => playback.control("rewind", { speed })}
            >
              Rewind
            </Button>
            <Select
              value={String(speed)}
              onChange={(e) => setSpeed(Number(e.target.value))}
              aria-label="Speed"
            >
              <option value="1">1×</option>
              <option value="2">2×</option>
              <option value="3">4×</option>
              <option value="4">8×</option>
              <option value="5">16×</option>
            </Select>
            <span className={styles.transportNote}>
              These commands are sent to the recorder. Whether it honors them depends on the
              device's firmware, and it answers on the device link rather than here.
            </span>
          </div>
        )}
      </Card>
    </div>
  );
}
