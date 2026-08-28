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
 * **No auto-reconnect** — the relay's viewer token is single-use
 * (`session/viewer_token.SingleUseTokenGuard.claim`); a fresh `POST /video/live` call (a new
 * token) is required after any close, mirroring `useRelayStreamSocket`'s own precedent exactly.
 */

export type MpegtsPlayerState = "idle" | "connecting" | "connected" | "closed" | "error";

export interface UseMpegtsPlayerResult {
  state: MpegtsPlayerState;
  /** A human-readable message from the most recent `mpegts.Events.ERROR`, `null` otherwise. */
  errorMessage: string | null;
}

export function useMpegtsPlayer(
  streamUrl: string | null,
  videoRef: RefObject<HTMLVideoElement>,
): UseMpegtsPlayerResult {
  const [state, setState] = useState<MpegtsPlayerState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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

    function handleError(type: unknown, detail: unknown): void {
      setState("error");
      setErrorMessage(`${String(type)}: ${String(detail)}`);
    }
    function handleMediaInfo(): void {
      setState((current) => (current === "connecting" ? "connected" : current));
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
      { type: "flv", isLive: true, url: streamUrl, hasVideo: true },
      { enableStashBuffer: false },
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
    // it runs, not a re-run whenever the *ref object's identity* changes.
  }, [streamUrl]);

  return { state, errorMessage };
}
