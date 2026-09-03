import { useEffect, useState, type RefObject } from "react";
import mpegts from "mpegts.js";

/**
 * Wraps `mpegts.js`'s MSE-based FLV player against the JT1078 relay's own WS-FLV viewer
 * endpoint (`services/jt1078/src/viewer/`) — the approved replacement for
 * `useRelayStreamSocket`'s raw-byte connectivity proof (`.claude/rules/workflow.md` #1/#2
 * proposal, approved: `mpegts.js@^1.8.2`, chosen over `flv.js` for active maintenance and no
 * webpack-specific transitive dependency under this project's Vite build).
 *
 * `mpegts.createPlayer` selects its `WebSocketLoader` purely off the `ws://`/`wss://` scheme in
 * `streamUrl` (confirmed against `xqq/mpegts.js`'s current `io-controller.js`) — the relay's
 * existing `stream_url` contract needs no change, and the loader's own binary-chunk handling
 * (`binaryType = 'arraybuffer'`, no requirement that a WS message align to a complete FLV tag)
 * matches `FlvMuxer`'s per-call tag framing exactly.
 *
 * **`hasAudio: false` is deliberate, not an oversight.** `services/jt1078/src/repackager/
 * flv_muxer.py`'s `build_aac_raw_tag` never emits an AAC sequence header (`AACPacketType=0`,
 * the `AudioSpecificConfig`) before its raw AAC tags — the video side has this via
 * `build_avc_sequence_header_tag`, audio does not. Feeding an audio track to the demuxer
 * without it is unreliable, so this hook plays video only until that relay-side gap is closed
 * separately (modifying the relay was explicitly out of scope for this phase).
 *
 * **The relay's WebSocket close code (e.g. `4001` invalid/used token, `4004`
 * `session_not_active`) is not recoverable through this library** — confirmed against
 * `WebSocketLoader`'s current `_onWebSocketClose`, which does not forward `CloseEvent.code`.
 * An unexpected close reaches this hook only as a generic `LOADING_COMPLETE` (mapped to
 * `"closed"` below); only a genuine `mpegts.Events.ERROR` (network/media/demux failure) is
 * mapped to `"error"`. `VideoPage.tsx`'s old close-code-based `unavailable`-vs-`error` split is
 * therefore collapsed into a single `"closed"` outcome here — a disclosed, deliberate loss of
 * diagnostic granularity versus the old raw-socket hook, not a silently dropped case.
 *
 * **No auto-reconnect at this layer** — the relay's viewer token is single-use
 * (`session/viewer_token.SingleUseTokenGuard.claim`); a fresh `POST /video/live` call (a new
 * token) is required after any close, mirroring `useRelayStreamSocket`'s own precedent exactly.
 * (`useVideoSessionController`'s own Phase 6 auto-recovery now does exactly that — request a
 * fresh session — one layer up, once this hook reports `"closed"`; this hook itself still never
 * retries the same, now-dead WebSocket connection.)
 *
 * **Live-latency tuning (Phase 5, 2026-09-02).** `enableStashBuffer: false` (kept, validated
 * unchanged — the low-latency choice, feeding MSE as data arrives rather than smoothing through
 * an internal buffer first) was previously the *only* latency control in play, and mpegts.js has
 * no way on its own to notice or correct for latency that gradually drifts upward over a long
 * session (the "video can accumulate latency / freeze / catch up" symptom this phase
 * investigates) — nothing here was watching the gap between the media element's own buffered
 * end and its `currentTime`. Two additions, both native `mpegts.js@^1.8.2` config, chosen over a
 * hand-rolled watchdog specifically because the library already implements this correctly:
 * - `liveSync: true` with a bounded `liveSyncMaxLatency`/`liveSyncTargetLatency` — once buffered
 *   latency exceeds the max, mpegts.js gently raises `HTMLMediaElement.playbackRate` (up to
 *   `liveSyncPlaybackRate`, default browser pitch-preservation keeps this from sounding
 *   chipmunk-ish) until latency is back down to the target, then returns to normal speed. Chosen
 *   over the library's older `liveBufferLatencyChasing` (a hard *seek* forward instead) because a
 *   seek is a visible jump/glitch — speed-based catch-up is smooth, which matters here for both
 *   ordinary live video and, since this hook is shared, an ADR-0036 intercom downlink where a
 *   jarring seek would be far more noticeable mid-conversation than a brief, barely-perceptible
 *   speed-up.
 * - `autoCleanupSourceBuffer` with bounded backward-duration limits — without this, a
 *   multi-minute session's own MSE `SourceBuffer` keeps every already-played second buffered
 *   forever, growing unboundedly; this only ever discards data already played, never anything
 *   still needed for live playback, so it cannot itself cause a freeze.
 * Deliberately conservative thresholds (seconds, not fractions of a second) so ordinary network
 * jitter never triggers a speed-up — only genuine, sustained latency drift does, per this phase's
 * own "tolerate reasonable jitter... prevent long freeze/catch-up cycles... do not turn the
 * player into delayed playback" targets.
 */

const LIVE_SYNC_MAX_LATENCY_SECONDS = 1.5;
const LIVE_SYNC_TARGET_LATENCY_SECONDS = 0.5;
const LIVE_SYNC_PLAYBACK_RATE = 1.2;
const AUTO_CLEANUP_MAX_BACKWARD_DURATION_SECONDS = 30;
const AUTO_CLEANUP_MIN_BACKWARD_DURATION_SECONDS = 10;

/** How long the media element's playback position may stand still before the picture is
 * declared stale. Comfortably above one frame interval at any realistic rate (and above the
 * ~1s GOP this platform's MDVR uses), so ordinary jitter never trips it, while still surfacing
 * a real freeze far faster than the relay's own 60s ingest-stall timeout could. */
const STALL_THRESHOLD_MS = 3000;
const STALL_POLL_MS = 1000;

export type MpegtsPlayerState = "idle" | "connecting" | "connected" | "closed" | "error";

export interface UseMpegtsPlayerResult {
  state: MpegtsPlayerState;
  /** A human-readable message from the most recent `mpegts.Events.ERROR`, `null` otherwise. */
  errorMessage: string | null;
  /** True while the player is `"connected"` but the media element's own playback position has
   * stopped advancing — i.e. the picture on screen is frozen (2026-09-02).
   *
   * **Why this is needed.** `state` latches to `"connected"` on the first `MEDIA_INFO` and only
   * leaves it on an error or a socket close, so it answers "did a frame ever decode?", never "is
   * video flowing *now*". Live-verified against the physical bench unit: a radio-link outage
   * stops media at the device while the viewer WebSocket stays open (median 28s, max 93s), so
   * the UI kept showing a confident "Live" badge over a frozen image with nothing indicating
   * staleness. `currentTime` is the honest signal — it is the decoder's own progress, so it
   * cannot claim liveness that isn't there. */
  stalled: boolean;
}

export interface UseMpegtsPlayerOptions {
  /** ADR-0036 (intercom). Defaults to `true` — every pre-existing caller (ordinary live/
   * playback video, always carrying video frames) keeps its exact current behavior unchanged.
   * An intercom session carries *only* audio frames (data_type=2 is audio-only on the wire,
   * confirmed live) — setting this `false` for it is required, not cosmetic: with `hasVideo:
   * true`, mpegts.js's own `isComplete()` gate waits forever for a video sequence header/
   * keyframe that will never arrive, and `MEDIA_INFO` (this hook's own `"connected"` signal)
   * never fires. */
  hasVideo?: boolean;
}

export function useMpegtsPlayer(
  streamUrl: string | null,
  // `HTMLMediaElement` (not `HTMLVideoElement`) - ADR-0036's intercom downlink attaches this to
  // an `<audio>` element (no picture, ever); mpegts.js's own `attachMediaElement` is element-
  // type-agnostic (it only needs the shared `HTMLMediaElement` playback surface), and every
  // pre-existing `<video>` caller is unaffected since `HTMLVideoElement` already satisfies this
  // wider type.
  videoRef: RefObject<HTMLMediaElement>,
  options: UseMpegtsPlayerOptions = {},
): UseMpegtsPlayerResult {
  const { hasVideo = true } = options;
  const [state, setState] = useState<MpegtsPlayerState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [stalled, setStalled] = useState(false);

  useEffect(() => {
    setErrorMessage(null);

    if (!streamUrl) {
      setState("idle");
      return;
    }

    const videoElement = videoRef.current;
    if (!videoElement) {
      setState("error");
      setErrorMessage("Video element was not ready to attach the player to.");
      return;
    }

    if (!mpegts.isSupported()) {
      setState("error");
      setErrorMessage("This browser does not support MSE-based H.264 playback.");
      return;
    }

    setState("connecting");

    const connectStartedAt = performance.now();

    function handleError(type: unknown, detail: unknown): void {
      setState("error");
      setErrorMessage(`${String(type)}: ${String(detail)}`);
      // eslint-disable-next-line no-console
      console.debug("[video:mpegts] ERROR", {
        type: String(type),
        detail: String(detail),
        elapsedMs: Math.round(performance.now() - connectStartedAt),
      });
    }
    function handleMediaInfo(): void {
      setState((current) => (current === "connecting" ? "connected" : current));
      // eslint-disable-next-line no-console
      console.debug("[video:mpegts] MEDIA_INFO (first frame ready)", {
        elapsedMs: Math.round(performance.now() - connectStartedAt),
      });
    }
    function handleLoadingComplete(): void {
      setState((current) => (current === "error" ? current : "closed"));
    }

    const player = mpegts.createPlayer(
      // `hasAudio` deliberately omitted (not `false`): mpegts.js auto-detects it per-stream -
      // stays `false` (video-only, today's exact behavior) unless a real audio tag actually
      // arrives, in which case it promotes to `true` on its own. Setting `false` explicitly
      // would have made `isComplete()` wait forever for audio metadata a video-only channel
      // never sends, silently blocking that channel's own video from ever starting.
      { type: "flv", isLive: true, url: streamUrl, hasVideo },
      {
        enableStashBuffer: false,
        liveSync: true,
        liveSyncMaxLatency: LIVE_SYNC_MAX_LATENCY_SECONDS,
        liveSyncTargetLatency: LIVE_SYNC_TARGET_LATENCY_SECONDS,
        liveSyncPlaybackRate: LIVE_SYNC_PLAYBACK_RATE,
        autoCleanupSourceBuffer: true,
        autoCleanupMaxBackwardDuration: AUTO_CLEANUP_MAX_BACKWARD_DURATION_SECONDS,
        autoCleanupMinBackwardDuration: AUTO_CLEANUP_MIN_BACKWARD_DURATION_SECONDS,
      },
    );
    player.on(mpegts.Events.ERROR, handleError);
    player.on(mpegts.Events.MEDIA_INFO, handleMediaInfo);
    player.on(mpegts.Events.LOADING_COMPLETE, handleLoadingComplete);

    try {
      player.attachMediaElement(videoElement);
      player.load();
      // `play()` is typed `void | Promise<void>` in mpegts.js's own d.ts — only a genuine
      // Promise needs the rejection swallowed (a rejected autoplay promise still leaves the
      // video element's own native "click to play" affordance available).
      player.play()?.catch(() => {});
    } catch (error) {
      handleError("OtherError", error instanceof Error ? error.message : String(error));
    }

    return () => {
      player.off(mpegts.Events.ERROR, handleError);
      player.off(mpegts.Events.MEDIA_INFO, handleMediaInfo);
      player.off(mpegts.Events.LOADING_COMPLETE, handleLoadingComplete);
      try {
        player.pause();
        player.unload();
        player.detachMediaElement();
        player.destroy();
      } catch {
        // Best-effort teardown, mirroring VideoPage.tsx's own `ensureStopped` posture — a
        // failed player teardown must never block the UI from resetting.
      }
    };
    // `videoRef` is deliberately excluded — a `RefObject` from `useRef` is stable across
    // renders by React's own contract, and this effect only needs its `.current` at the moment
    // it runs, not a re-run whenever the *ref object's identity* changes. `hasVideo` is included
    // since a caller could in principle pass a differently-shaped `options` object across
    // renders (though every real caller today passes the same value for the hook's whole
    // lifetime, live/playback `true`, intercom `false`).
  }, [streamUrl, hasVideo]);

  // Frozen-picture detection. Deliberately driven by `HTMLMediaElement.currentTime` rather than
  // mpegts.js's own STATISTICS_INFO counters: `currentTime` is what the user is actually
  // watching advance (or not), and it stays correct for the audio-only intercom downlink too,
  // where there are no decoded *video* frames to count. Only ever runs while `"connected"`, so
  // it can never contradict a real error/closed state.
  useEffect(() => {
    if (state !== "connected") {
      setStalled(false);
      return;
    }
    let lastPosition = videoRef.current?.currentTime ?? 0;
    let lastAdvancedAt = Date.now();
    const timerId = window.setInterval(() => {
      const element = videoRef.current;
      if (!element) return;
      const position = element.currentTime;
      if (position !== lastPosition) {
        lastPosition = position;
        lastAdvancedAt = Date.now();
        setStalled(false);
        return;
      }
      // A deliberately paused element is not a stall — the operator stopped it themselves
      // (`CameraTile`'s own pause affordance), and reporting that as "no signal" would be a lie.
      if (element.paused) {
        lastAdvancedAt = Date.now();
        return;
      }
      if (Date.now() - lastAdvancedAt >= STALL_THRESHOLD_MS) setStalled(true);
    }, STALL_POLL_MS);
    return () => window.clearInterval(timerId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, streamUrl]);

  return { state, errorMessage, stalled };
}
