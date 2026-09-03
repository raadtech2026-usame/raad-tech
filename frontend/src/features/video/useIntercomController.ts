import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { useMutation } from "@tanstack/react-query";
import { useToast } from "../../shared/components/Toast/toastStore";
import {
  createUplinkFrameChunkerState,
  encodeFloat32ToALaw,
  flushPendingFrame,
  pushAndDrainFrames,
  resampleFloat32Linear,
  type UplinkFrameChunkerState,
} from "../../shared/audio/g711a";
import { ApiError } from "../../shared/api/types";
import { requestIntercom, stopVideoSession, type VideoSession } from "./api";
import { useMpegtsPlayer } from "./useMpegtsPlayer";

/**
 * ADR-0036 — the intercom session lifecycle + browser microphone capture/uplink half of "Talk to
 * Driver". Mirrors `useVideoSessionController.ts`'s own request/teardown/phase-machine shape for
 * the parts they share (`POST /video/intercom` vs. `POST /video/live`, both torn down via the
 * same `POST /video/sessions/{id}/stop`), but adds a second, genuinely new capability neither
 * live video nor playback needs: capturing and transmitting the operator's own mic audio.
 *
 * **Two independent WebSocket connections, not one** (ADR-0036 §5): `session.streamUrl` (the
 * existing, unmodified viewer contract) plays the bus mic's own audio via `useMpegtsPlayer`,
 * exactly like live video's downlink; `session.uplinkUrl` is a second, separately-tokened raw
 * `WebSocket` this hook manages itself, carrying only the operator's own encoded mic audio
 * upstream. A session's viewer token is single-use, so these cannot share one connection.
 *
 * **Push-to-talk, not a hot mic.** The microphone stream is captured once the session reaches
 * `"connected"` (so the UI can show a real "mic ready" state), but audio frames are only ever
 * encoded and sent while `isTransmitting` is true — gated entirely by `startTalking`/
 * `stopTalking`, never sent just because the stream exists. This matches the explicit requirement
 * to "clearly show when the operator microphone is transmitting," never silently.
 *
 * **Bug 1 fix — the relay now actively closes both sockets when the backend session becomes
 * terminal** (`services/jt1078/src/relay.py._on_session_removed`, close code `4010` for FAILED /
 * `4011` for ENDED, reason bytes carrying the actual reason string, e.g. `"ingest_timeout"`).
 * Before this fix, a session that failed asynchronously (the device never opened the ingest
 * connection, relay-side 30s timeout) left this hook's own sockets open and silent forever —
 * `phase` had no way to leave `"connecting"`. `uplinkSocketRef`'s own `onclose` handler below is
 * the one place this hook can reliably read a `CloseEvent`'s `code`/`reason` (the downlink half
 * goes through `useMpegtsPlayer`/`mpegts.js`, which — per that hook's own documented limitation —
 * collapses every close into a generic `"closed"` state with no code; kept as a secondary,
 * lower-priority fallback below, not the primary signal). A close code that isn't one of the two
 * server-driven codes (e.g. `1000` from this hook's own `teardownUplinkSocket`) is deliberately
 * ignored here — `stop()` already drives `phase` to `"stopped"` via `manuallyStopped` before ever
 * closing the socket itself, so there is nothing for this handler to add for that path.
 *
 * **Bug 2 fix (2026-09-02) — uplink packetization.** `CAPTURE_BUFFER_SIZE` (2048) is a Web Audio
 * `ScriptProcessorNode` buffer-size choice (one of the API's own valid power-of-two options), not
 * a wire-framing decision — encoding and sending an entire 2048-sample callback as one WebSocket
 * message produced up to 2048-byte G.711A payloads, well past `services/jt1078/src/ingest/
 * extended_rtp.py`'s own 950-byte extended-RTP body ceiling, raising
 * `MalformedExtendedRtpFrameError` relay-side and closing the uplink socket — proven live against
 * the physical bench unit before this fix. `onaudioprocess` below now runs every encoded batch
 * through `pushAndDrainFrames` (`shared/audio/g711a.ts`), a persistent carry-over chunker that
 * emits fixed `UPLINK_FRAME_SIZE_BYTES` (320 — ADR-0033's own confirmed device frame size, 40ms
 * at 8kHz) frames and keeps any remainder buffered for the next callback — no sample is ever
 * dropped between callbacks, and no frame this hook sends can ever exceed the relay's ceiling.
 * `stopTalking()` flushes whatever partial frame is left buffered so the last fraction of a
 * second of speech before the operator releases Talk is not silently lost.
 *
 * **Bug 3 fix (2026-09-02) — duplicate capture pipelines on repeated Hold-to-Talk.**
 * `stopTalking()` deliberately never tears the mic/`AudioContext`/`ScriptProcessorNode` down (so
 * a fast re-press has no `getUserMedia` round-trip latency) — but `startTalking()` used to build
 * a brand-new pipeline on *every* call regardless, with no check for one already existing. A
 * second Hold-to-Talk press within the same session therefore left the *first* press's own
 * pipeline running forever (never referenced again, never closed) while a *second*, independent
 * one was built alongside it — both actively capturing the same microphone and both writing into
 * the same shared `uplinkChunkerRef` the moment `transmittingRef` went `true` again, interleaving
 * two overlapping audio streams into one uplink socket. This is the confirmed, physically-tested
 * root cause of "browser→MDVR audio sometimes noisy/distorted, spoken word repeats several
 * times." `startTalking()` now reuses an already-built pipeline (checking `processorRef`/
 * `audioContextRef`/`micStreamRef` before ever calling `getUserMedia` again) — there is
 * structurally only ever at most one live pipeline per session, so there is nothing left for a
 * second press to duplicate.
 */

export type IntercomPhase =
  | "idle"
  | "requesting"
  | "connecting"
  | "connected"
  | "stopping"
  | "stopped"
  | "failed"
  | "ended"
  | "unavailable"
  | "error";

/** Matches `services/jt1078/src/relay.py`'s own `_CLOSE_CODE_SESSION_FAILED`/
 * `_CLOSE_CODE_SESSION_ENDED` exactly — see that module's comment for why these are two distinct
 * codes rather than one generic "session terminal" code. */
const CLOSE_CODE_SESSION_FAILED = 4010;
const CLOSE_CODE_SESSION_ENDED = 4011;

export interface IntercomTerminalEvent {
  type: "failed" | "ended";
  /** The relay's own close `reason` bytes, decoded — e.g. `"ingest_timeout"`,
   * `"business_api_requested"`, `"viewer_idle_timeout"`. Empty string if the close frame carried
   * no reason (should not happen for a server-driven close, but never assumed). */
  reason: string;
}

/** Why microphone capture failed, classified from the `getUserMedia` rejection's own `name`
 * rather than its message text (messages are browser-specific and localised). Each maps to a
 * different operator action, which is the whole point of distinguishing them: "blocked", "none
 * connected" and "in use elsewhere" need three different responses, and previously all three
 * surfaced as one vague string. */
export type MicFailureKind =
  | "permission-denied"
  | "no-device"
  | "device-busy"
  | "device-gone"
  | "aborted"
  | "unsupported"
  | "unknown";

/** Talk is pointless in these two states — there is nothing to capture from until the operator
 * changes something outside RAAD, so the button is disabled rather than failing on every press. */
const MIC_FATAL_FAILURES: ReadonlySet<MicFailureKind> = new Set<MicFailureKind>([
  "permission-denied",
  "no-device",
]);

const MIC_FAILURE_MESSAGE: Record<MicFailureKind, string> = {
  "permission-denied":
    "Microphone access is blocked. Allow it from the microphone icon in your browser's address bar, then press Talk again.",
  "no-device":
    "No microphone was found on this computer. Connect one to talk to the driver.",
  "device-busy":
    "The microphone is being used by another application. Close it, then press Talk again.",
  "device-gone":
    "That microphone is no longer available — switched back to the system default.",
  aborted: "The microphone could not be started. Press Talk to try again.",
  unsupported: "This browser does not support microphone capture.",
  unknown: "Could not access the microphone.",
};

/** Maps a DOMException name to our own kind. `OverconstrainedError` is the one that matters most
 * operationally: it is what a *previously chosen* device that has since been unplugged produces,
 * and it must never leave intercom broken. */
/** The single place RAAD asks for a microphone. With no `deviceId` this is exactly the generic
 * `{ audio: true }` request the architecture decision mandates — the browser resolves whatever
 * the OS considers default, and RAAD names no hardware. */
async function requestMicrophone(deviceId: string | null): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      channelCount: 1,
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
    },
  });
}

function classifyMicFailure(error: unknown): MicFailureKind {
  const name = (error as { name?: string } | null)?.name;
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "permission-denied";
    case "NotFoundError":
      return "no-device";
    case "NotReadableError":
      return "device-busy";
    case "OverconstrainedError":
    case "ConstraintNotSatisfiedError":
      return "device-gone";
    case "AbortError":
      return "aborted";
    default:
      return "unknown";
  }
}

export interface IntercomRequestError {
  message: string;
  /** Mirrors `VideoRequestError.unavailable` (`useVideoSessionController.ts`) — a missing
   * `VideoProviderPort` and a genuine unexpected error are indistinguishable at the HTTP layer
   * (both 500), so this is "unavailable," not claimed as certainly one or the other. */
  unavailable: boolean;
  /** ADR-0036 §2 — a 409 from the backend's own one-active-intercom-session-per-device check:
   * someone else is already talking to this bus. Surfaced distinctly so the UI can say exactly
   * that, not a generic error. */
  alreadyInUse: boolean;
}

export interface UseIntercomControllerResult {
  phase: IntercomPhase;
  requestError: IntercomRequestError | null;
  /** Set only when `phase` is `"failed"`/`"ended"` — the relay's own reported reason (Bug 1 fix),
   * for `IntercomControl.tsx` to render something more specific than a generic message. */
  terminalEvent: IntercomTerminalEvent | null;
  micError: string | null;
  /** True only while the Talk button is actively held and mic frames are being sent — the one
   * signal the UI must render unmistakably (never inferred from `phase` alone). */
  isTransmitting: boolean;
  /** For hearing the bus mic — attach to an `<audio>` (or `<video>`) element, exactly like
   * `useVideoSessionController`'s own `videoRef`. */
  audioRef: RefObject<HTMLAudioElement>;
  /** Live microphone level while transmitting, 0..1 (RMS of the same resampled 8kHz PCM that is
   * about to be G.711A-encoded and sent). `0` when not transmitting. **This is the operator's
   * only feedback that their microphone is actually producing sound** — live-diagnosed
   * 2026-09-03, when Chromium had silently selected a virtual "Voice Changer" input device that
   * output exact zeros: every layer reported success, 135 correctly-framed packets reached the
   * MDVR, and nothing anywhere indicated the audio was digital silence. */
  micLevel: number;
  /** True once we have been transmitting for `SILENT_MIC_WARNING_MS` with the level still at the
   * floor — i.e. the mic is connected and delivering buffers, but they contain nothing. */
  micSilent: boolean;
  /** The label of the input device actually in use (`MediaStreamTrack.label`), so the operator
   * can see at a glance that it is not the device they expected. `null` before capture starts. */
  micDeviceLabel: string | null;
  /** Classified reason microphone capture failed, `null` when fine. Distinct from `micError`
   * (the human message) so callers can branch on the cause without parsing text. */
  micFailure: MicFailureKind | null;
  /** True when Talk cannot work at all until the operator changes something outside RAAD
   * (permission blocked, or no input device exists) — the Talk button is disabled. */
  micUnavailable: boolean;
  /** Every available audio input, for the picker. Populated on demand. */
  micDevices: MediaDeviceInfo[];
  /** Currently selected `deviceId`, or `null` for the browser default. */
  selectedMicDeviceId: string | null;
  /** Switches input device. Tears down any existing capture pipeline so the next Talk press
   * acquires the newly chosen microphone. */
  selectMicDevice: (deviceId: string | null) => void;
  canStart: boolean;
  canStop: boolean;
  start: () => void;
  stop: () => Promise<void>;
  startTalking: () => Promise<void>;
  stopTalking: () => void;
  /** Click-to-talk toggle — starts if idle, stops if transmitting. Idempotent against
   * double-clicks. Preferred over calling `startTalking`/`stopTalking` directly. */
  toggleTalking: () => void;
  /** Whole seconds left before the hard stop fires, `0` when not transmitting. Display only. */
  talkSecondsRemaining: number;
  /** The hard ceiling, exposed so the UI never has to restate the number. */
  maxTalkSeconds: number;
}

const UPLINK_SAMPLE_RATE_HZ = 8000; // ADR-0033's own confirmed device rate
const CAPTURE_BUFFER_SIZE = 2048; // ScriptProcessorNode's own valid power-of-two options
// ADR-0033's own confirmed G.711A audio_frame_length (40ms at 8kHz mono, 1 byte/sample) — the
// wire-framing unit `pushAndDrainFrames` packetizes every capture callback into (Bug 2 fix).
// Deliberately independent of CAPTURE_BUFFER_SIZE above: 2048 raw samples is a Web Audio API
// buffer-size constant, not a multiple of this frame size, hence the persistent carry-over
// chunker rather than a fixed per-callback split.
const UPLINK_FRAME_SIZE_BYTES = 320;
/** How often the audio callback's measured level is published to React. The callback itself runs
 * ~23x/second at 48kHz/2048; re-rendering that fast would be wasteful, so the level is kept in a
 * ref and sampled on this interval instead. */
const MIC_LEVEL_PUBLISH_MS = 100;
/** How long a continuously-silent microphone must stay silent while transmitting before the UI
 * says so. Long enough not to fire on a natural pause between words. */
const SILENT_MIC_WARNING_MS = 1500;
/** RMS below this (of full scale 1.0) is treated as "no signal at all". A live microphone in a
 * quiet room still sits well above this; the virtual device that caused the 2026-09-03 incident
 * produced exact 0. */
const MIC_SILENCE_RMS = 0.0015;
/** Hard ceiling on a single transmission (2026-09-03, click-to-talk model). With Hold-to-Talk the
 * button being released *was* the stop signal; a click-to-start model has no such guarantee, so an
 * operator who clicks TALK and walks away would otherwise hold an open microphone to the bus
 * indefinitely. This is enforced as a real lifecycle timer that runs the ordinary `stopTalking()`
 * teardown - flushing the final partial G.711A frame exactly as a manual stop does - not as a UI
 * countdown that merely looks like it expired. */
const MAX_TALK_DURATION_MS = 10_000;

function classifyRequestError(error: unknown): IntercomRequestError {
  const apiError = error instanceof ApiError ? error : null;
  return {
    message: apiError?.message ?? "Could not start the intercom session.",
    unavailable: apiError?.status === 500,
    alreadyInUse: apiError?.status === 409,
  };
}

export function useIntercomController(
  deviceId: string | null,
  cameraId: string | null,
): UseIntercomControllerResult {
  const toast = useToast();
  const [session, setSession] = useState<VideoSession | null>(null);
  const [manuallyStopped, setManuallyStopped] = useState(false);
  const [requestError, setRequestError] = useState<IntercomRequestError | null>(null);
  const [terminalEvent, setTerminalEvent] = useState<IntercomTerminalEvent | null>(null);
  const [micError, setMicError] = useState<string | null>(null);
  const [micFailure, setMicFailure] = useState<MicFailureKind | null>(null);
  const [isTransmitting, setIsTransmitting] = useState(false);
  const stoppedSessionIdsRef = useRef<Set<string>>(new Set());

  const uplinkSocketRef = useRef<WebSocket | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const transmittingRef = useRef(false); // read inside the audio-processing callback
  // Bug 2 fix — persistent carry-over state for `pushAndDrainFrames`, owned per-hook-instance so
  // concurrent intercom controllers (should that ever happen) never share buffered audio bytes.
  const uplinkChunkerRef = useRef<UplinkFrameChunkerState>(createUplinkFrameChunkerState());
  // Bug 3 fix (2026-09-02) — guards the async gap inside `startTalking` itself (`getUserMedia`
  // is awaited before `transmittingRef`/`processorRef` are ever set) so two near-simultaneous
  // presses can never both reach the pipeline-construction branch and build two independent
  // capture pipelines. Distinct from `transmittingRef`, which only guards *after* a pipeline
  // already exists.
  const startingTalkRef = useRef(false);
  //: Lets the `devicechange` effect resume transmission after a forced teardown without taking
  //: `startTalking` as a dependency (it is redefined every render).
  const startTalkingRef = useRef<(() => Promise<void>) | null>(null);
  const stopTalkingRef = useRef<(() => void) | null>(null);
  //: The hard-stop timer and the moment this transmission began. Both are cleared by every path
  //: that ends transmission (manual stop, timeout, mic teardown, session loss, unmount) so no
  //: orphan timer can ever fire against a later, unrelated talk session.
  const talkTimeoutRef = useRef<number | null>(null);
  const talkStartedAtRef = useRef<number | null>(null);
  const [talkSecondsRemaining, setTalkSecondsRemaining] = useState(0);
  //: Mic metering. The level is written by the audio callback (~23x/sec) into a ref and only
  //: published to React on an interval, so metering never drives the render loop.
  const micLevelRef = useRef(0);
  const [micLevel, setMicLevel] = useState(0);
  const [micSilent, setMicSilent] = useState(false);
  const [micDeviceLabel, setMicDeviceLabel] = useState<string | null>(null);
  const [micDevices, setMicDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedMicDeviceId, setSelectedMicDeviceId] = useState<string | null>(null);
  const loudSinceRef = useRef<number>(Date.now());

  const startMutation = useMutation({
    mutationFn: () => requestIntercom(deviceId as string, cameraId as string),
    onSuccess: (newSession) => {
      setSession(newSession);
      setManuallyStopped(false);
      setRequestError(null);
      setTerminalEvent(null);
    },
    onError: (error: unknown) => {
      setRequestError(classifyRequestError(error));
    },
  });

  const clearTalkTimeout = useCallback(() => {
    if (talkTimeoutRef.current !== null) {
      window.clearTimeout(talkTimeoutRef.current);
      talkTimeoutRef.current = null;
    }
    talkStartedAtRef.current = null;
    setTalkSecondsRemaining(0);
  }, []);

  const teardownMic = useCallback(() => {
    clearTalkTimeout();
    transmittingRef.current = false;
    setIsTransmitting(false);
    processorRef.current?.disconnect();
    processorRef.current = null;
    audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
    micLevelRef.current = 0;
    setMicLevel(0);
    setMicSilent(false);
    setMicDeviceLabel(null);
    // Bug 2 fix — never carry buffered-but-unsent audio bytes across a teardown into a future,
    // unrelated talk session (a fresh `startTalking()` call already resets this too; this is the
    // safety net for the `startTalking()` catch-block and unmount/session-teardown paths).
    uplinkChunkerRef.current = createUplinkFrameChunkerState();
  }, [clearTalkTimeout]);

  const teardownUplinkSocket = useCallback(() => {
    uplinkSocketRef.current?.close();
    uplinkSocketRef.current = null;
  }, []);

  async function ensureStopped(sessionId: string, options?: { keepalive?: boolean }): Promise<void> {
    if (stoppedSessionIdsRef.current.has(sessionId)) return;
    stoppedSessionIdsRef.current.add(sessionId);
    try {
      await stopVideoSession(sessionId, options);
    } catch {
      // Best-effort teardown, mirroring useVideoSessionController's identical posture - a
      // failed stop must never block the UI from resetting. If this call never even reaches
      // the backend at all (tab closed mid-flight, network dropped), the backend's own
      // `reconcile_stale_intercom_sessions` scheduled job is the real, structural guarantee
      // this session can't block another operator forever - `keepalive` below is a latency
      // improvement on top of that, not a substitute for it.
    }
  }

  // Tears down whatever session was open before this render's selection - mirrors
  // useVideoSessionController's own identical cleanup effect exactly, plus mic/uplink teardown.
  useEffect(() => {
    return () => {
      teardownMic();
      teardownUplinkSocket();
      if (session && !manuallyStopped) {
        // `keepalive: true` (ADR-0037) - this cleanup fires on unmount, which includes a tab
        // close/navigation-away, not just an ordinary re-render; without it the browser can
        // abort the request mid-flight the instant the page starts unloading.
        void ensureStopped(session.id, { keepalive: true });
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, manuallyStopped]);

  useEffect(() => {
    setSession(null);
    setManuallyStopped(false);
    setRequestError(null);
    setTerminalEvent(null);
    setMicError(null);
    teardownMic();
    teardownUplinkSocket();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId, cameraId]);

  const downlinkUrl = session && !manuallyStopped ? session.streamUrl : null;
  const uplinkUrl = session && !manuallyStopped ? (session.uplinkUrl ?? null) : null;
  const audioRef = useRef<HTMLAudioElement>(null);
  // ADR-0036: hasVideo: false - an intercom session carries only audio frames on the wire.
  const player = useMpegtsPlayer(downlinkUrl, audioRef, { hasVideo: false });

  // Opens the uplink WebSocket the moment a session exists - kept open for the session's whole
  // lifetime (not per Talk press) so pressing Talk has no connection-handshake latency.
  useEffect(() => {
    if (!uplinkUrl) return;
    const socket = new WebSocket(uplinkUrl);
    socket.binaryType = "arraybuffer";
    // Bug 1 fix: the relay closes this socket with code 4010 (FAILED)/4011 (ENDED) the instant
    // the backend session becomes terminal (`relay.py._on_session_removed`) — any other code
    // (1000 from this hook's own `teardownUplinkSocket`, or an ordinary network drop) is left
    // alone; `manuallyStopped`/`stop()` already drives the correct phase for an own-initiated
    // close, and an unrecognized code has nothing more specific this hook can say.
    socket.onclose = (event) => {
      if (event.code === CLOSE_CODE_SESSION_FAILED) {
        setTerminalEvent({ type: "failed", reason: event.reason });
      } else if (event.code === CLOSE_CODE_SESSION_ENDED) {
        setTerminalEvent({ type: "ended", reason: event.reason });
      }
    };
    uplinkSocketRef.current = socket;
    return () => {
      socket.onclose = null;
      socket.close();
      if (uplinkSocketRef.current === socket) uplinkSocketRef.current = null;
    };
  }, [uplinkUrl]);

  // Publishes the metered level to React at a human-visible rate, and decides when a
  // persistently-flat level should be surfaced as "no signal". Only runs while transmitting, so
  // an idle session never re-renders on a timer.
  useEffect(() => {
    if (!isTransmitting) {
      setMicLevel(0);
      setMicSilent(false);
      return;
    }
    loudSinceRef.current = Date.now();
    const timerId = window.setInterval(() => {
      setMicLevel(micLevelRef.current);
      setMicSilent(Date.now() - loudSinceRef.current > SILENT_MIC_WARNING_MS);
      // Display only - the authoritative stop is `armTalkTimeout`'s own `setTimeout`, so a
      // throttled/backgrounded tab still stops on time even if this interval is starved.
      const startedAt = talkStartedAtRef.current;
      if (startedAt !== null) {
        const left = MAX_TALK_DURATION_MS - (Date.now() - startedAt);
        setTalkSecondsRemaining(Math.max(0, Math.ceil(left / 1000)));
      }
    }, MIC_LEVEL_PUBLISH_MS);
    return () => window.clearInterval(timerId);
  }, [isTransmitting]);

  // Hot-plug handling (Option C, 2026-09-03). A headset unplugged mid-call, or a USB mic
  // connected, previously went entirely unnoticed: the device list went stale and an explicitly
  // selected device that had disappeared only surfaced as a generic error on the next press.
  //
  // **Deliberately never guesses a replacement by name.** The only action taken automatically is
  // falling back to the system default when the *explicitly chosen* device is gone — matching a
  // different device by label would be exactly the brittle, locale-dependent heuristic the
  // architecture decision rules out.
  useEffect(() => {
    const media = navigator.mediaDevices;
    if (!media?.addEventListener || !media.enumerateDevices) return;

    let cancelled = false;
    const onDeviceChange = (): void => {
      void media
        .enumerateDevices()
        .then((all) => {
          if (cancelled) return;
          const inputs = all.filter((d) => d.kind === "audioinput");
          setMicDevices(inputs);
          if (!selectedMicDeviceId) return;
          if (inputs.some((d) => d.deviceId === selectedMicDeviceId)) return;
          // The chosen device is gone. Release the pipeline so the next press re-acquires the
          // default; `teardownMic` also clears `transmittingRef`, so the re-acquisition below
          // builds exactly one new pipeline rather than racing a second alongside the old.
          const wasTransmitting = transmittingRef.current;
          setSelectedMicDeviceId(null);
          setMicFailure("device-gone");
          setMicError(MIC_FAILURE_MESSAGE["device-gone"]);
          teardownMic();
          if (wasTransmitting) void startTalkingRef.current?.();
        })
        .catch(() => {});
    };

    media.addEventListener("devicechange", onDeviceChange);
    return () => {
      cancelled = true;
      media.removeEventListener("devicechange", onDeviceChange);
    };
  }, [selectedMicDeviceId, teardownMic]);

  const selectMicDevice = useCallback(
    (deviceId: string | null) => {
      setSelectedMicDeviceId(deviceId);
      // Drop the existing pipeline so the next Talk press re-acquires with the new device.
      // `startTalking` reuses a live pipeline by design (Bug 3 fix), so without this teardown a
      // device change would silently not take effect until the session ended.
      teardownMic();
    },
    [teardownMic],
  );

  async function stop(): Promise<void> {
    if (!session) return;
    setManuallyStopped(true);
    teardownMic();
    teardownUplinkSocket();
    await ensureStopped(session.id);
    toast.info("Intercom stopped", "The intercom session has been stopped.");
  }

  function start(): void {
    startMutation.mutate();
  }

  /** Arms the hard stop. Deliberately routed through `stopTalkingRef` rather than calling
   * `stopTalking` directly, so the timeout runs the *same* teardown a manual stop does - final
   * partial G.711A frame flushed, transmitting state cleared, timer released - instead of a
   * second, parallel stop path that could drift from it. */
  function armTalkTimeout(): void {
    clearTalkTimeout();
    talkStartedAtRef.current = Date.now();
    setTalkSecondsRemaining(Math.round(MAX_TALK_DURATION_MS / 1000));
    talkTimeoutRef.current = window.setTimeout(() => {
      talkTimeoutRef.current = null;
      stopTalkingRef.current?.();
    }, MAX_TALK_DURATION_MS);
  }

  async function startTalking(): Promise<void> {
    // Bug 3 fix — `transmittingRef` alone only guards *after* a pipeline exists; a second press
    // landing during the `await getUserMedia(...)` gap below (before either ref is set) would
    // pass that check too and race a second pipeline into existence. `startingTalkRef` closes
    // that gap; both are checked so a caller can never re-enter this function while either a
    // pipeline is being built or one is already actively transmitting.
    if (transmittingRef.current || startingTalkRef.current) return;
    startingTalkRef.current = true;
    setMicError(null);
    setMicFailure(null);
    try {
      // Bug 3 fix — reuse the existing capture pipeline (mic stream, AudioContext,
      // ScriptProcessorNode) if one is already set up from an earlier Hold-to-Talk press this
      // session, instead of building a second, independent one alongside it. The previous
      // behavior left every prior press's own pipeline running forever (`stopTalking` only ever
      // flips `transmittingRef` to `false`, by design, so the mic stays warm for a fast re-press
      // - it never tore the pipeline down) - a second press therefore created a *second* live
      // `AudioContext`/`ScriptProcessorNode` capturing the same microphone, both writing into the
      // same shared `uplinkChunkerRef` concurrently once transmitting resumed. That interleaving
      // is exactly what produced the physically-confirmed "noisy/distorted, spoken word repeats
      // several times" symptom on any press after the first. Reusing the pipeline also avoids a
      // redundant `getUserMedia` round-trip on every press, keeping press-to-transmit latency low.
      if (processorRef.current && audioContextRef.current && micStreamRef.current) {
        const audioContext = audioContextRef.current;
        if (audioContext.state === "suspended") {
          // Some browsers auto-suspend an idle AudioContext; resuming is a no-op if it wasn't.
          await audioContext.resume();
        }
        // Fresh carry-over state for this press - never carries a partial frame left over from
        // a previous press into a new one (the previous press's own tail was already flushed by
        // `stopTalking`, but this stays correct even if that ever changes).
        uplinkChunkerRef.current = createUplinkFrameChunkerState();
        armTalkTimeout();
        transmittingRef.current = true;
        setIsTransmitting(true);
        return;
      }

      // Normal operation asks for a *generic* microphone — `{ audio: true }` shaped, with no
      // device named — so RAAD never assumes a vendor, chipset or platform. A `deviceId` is only
      // ever added when the operator explicitly picked one, and `exact` is deliberate there:
      // silently substituting a different device is the failure this picker exists to prevent.
      // If that chosen device has since vanished the browser raises `OverconstrainedError`,
      // which we recover from below rather than leaving intercom broken.
      let stream: MediaStream;
      try {
        stream = await requestMicrophone(selectedMicDeviceId);
      } catch (error) {
        if (classifyMicFailure(error) !== "device-gone") throw error;
        // The explicitly-chosen device is gone (unplugged headset, removed virtual device).
        // Drop the selection, fall back to the system default, and say so - never strand the
        // operator on a device that no longer exists.
        setSelectedMicDeviceId(null);
        setMicFailure("device-gone");
        setMicError(MIC_FAILURE_MESSAGE["device-gone"]);
        stream = await requestMicrophone(null);
      }
      micStreamRef.current = stream;
      // Purely informational, and deliberately defensive: the device label must never be able to
      // break audio capture. `getAudioTracks` is part of the MediaStream API but a non-standard
      // or partial implementation returning nothing here would otherwise throw straight into
      // `startTalking`'s catch block and tear down a perfectly good pipeline.
      setMicDeviceLabel(stream.getAudioTracks?.()?.[0]?.label || null);
      // Labels are only populated once permission has been granted, so this enumeration is
      // deliberately done *after* getUserMedia rather than on mount.
      void navigator.mediaDevices
        ?.enumerateDevices?.()
        .then((all) => setMicDevices(all.filter((d) => d.kind === "audioinput")))
        .catch(() => {});

      const AudioContextCtor =
        window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext;
      if (!AudioContextCtor) {
        throw new Error("This browser does not support Web Audio capture.");
      }
      // **Deliberately constructed at the browser's own native rate (2026-09-03).** This used
      // to request `{ sampleRate: UPLINK_SAMPLE_RATE_HZ }` (8000). Wire-captured proof that this
      // was wrong: during a 10-second Hold-to-Talk press with continuous speech, the relay
      // forwarded 712 correctly-framed 320-byte G.711A packets to the MDVR at exactly 25/sec,
      // the device ACKed all 236,998 bytes - and 99.6% of the payload was `0xD5`/`0x55`, A-law
      // positive/negative zero. Decoded amplitude: mean 8, max 248, against a full scale of
      // ~32768. The graph was running at precisely the right rate and delivering silence.
      // Forcing a non-native rate on an `AudioContext` that a `MediaStreamAudioSourceNode` feeds
      // is a known Chromium failure mode - the mic track is resampled internally and can arrive
      // as near-zero. `resampleFloat32Linear` already converts whatever rate we actually get
      // down to 8kHz on every callback (it was written for exactly this "the browser may ignore
      // the request" case), so requesting the rate here bought nothing and cost all the audio.
      const audioContext = new AudioContextCtor();
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(CAPTURE_BUFFER_SIZE, 1, 1);
      processorRef.current = processor;
      // Bug 2 fix — fresh carry-over state for this talk session (defensive; `teardownMic` and
      // `stopTalking` already clear it, but a `startTalking` after those never assumes it).
      uplinkChunkerRef.current = createUplinkFrameChunkerState();

      processor.onaudioprocess = (event) => {
        if (!transmittingRef.current) return;
        const socket = uplinkSocketRef.current;
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        const raw = event.inputBuffer.getChannelData(0);
        const resampled = resampleFloat32Linear(
          raw,
          audioContext.sampleRate,
          UPLINK_SAMPLE_RATE_HZ,
        );
        // Level is measured on the resampled 8kHz PCM - the exact samples about to be encoded
        // and sent - so the meter cannot disagree with what actually goes on the wire.
        let sumSquares = 0;
        for (let i = 0; i < resampled.length; i += 1) sumSquares += resampled[i] * resampled[i];
        micLevelRef.current = resampled.length ? Math.sqrt(sumSquares / resampled.length) : 0;
        if (micLevelRef.current > MIC_SILENCE_RMS) loudSinceRef.current = Date.now();

        const encoded = encodeFloat32ToALaw(resampled);
        // Bug 2 fix — never send `encoded` (up to 2048 bytes) directly; packetize into
        // <=950-byte (preferably exactly 320-byte) extended-RTP-safe frames instead, carrying
        // any remainder into the next callback rather than dropping or oversending it.
        const frames = pushAndDrainFrames(
          uplinkChunkerRef.current,
          encoded,
          UPLINK_FRAME_SIZE_BYTES,
        );
        for (const frame of frames) {
          socket.send(frame);
        }
      };

      source.connect(processor);
      // A ScriptProcessorNode only fires while connected into a live graph reaching the
      // destination - connecting to a muted/zero-gain node (rather than the real speakers)
      // avoids the operator hearing their own mic looped back locally.
      const silentSink = audioContext.createGain();
      silentSink.gain.value = 0;
      processor.connect(silentSink);
      silentSink.connect(audioContext.destination);

      armTalkTimeout();
      transmittingRef.current = true;
      setIsTransmitting(true);
    } catch (error) {
      teardownMic();
      // Classified from the DOMException `name`, never its message text: messages are
      // browser-specific and localised, while the names are specified. Each kind maps to a
      // different operator action - see `MIC_FAILURE_MESSAGE`.
      const kind =
        error instanceof Error && error.message.includes("does not support")
          ? "unsupported"
          : classifyMicFailure(error);
      setMicFailure(kind);
      setMicError(MIC_FAILURE_MESSAGE[kind]);
    } finally {
      startingTalkRef.current = false;
    }
  }

  startTalkingRef.current = startTalking;

  function stopTalking(): void {
    // Cleared first, so a stop that races the hard-stop timer can never leave it armed against
    // the *next* transmission.
    clearTalkTimeout();
    transmittingRef.current = false;
    setIsTransmitting(false);
    // Bug 2 fix — flush whatever partial (<320-byte) frame is still buffered so the last
    // fraction of a second of speech before the operator releases Talk is not silently dropped;
    // a short final frame is still a valid, well-under-950-byte extended-RTP audio body.
    const socket = uplinkSocketRef.current;
    const finalFrame = flushPendingFrame(uplinkChunkerRef.current);
    if (finalFrame && socket && socket.readyState === WebSocket.OPEN) {
      socket.send(finalFrame);
    }
  }

  stopTalkingRef.current = stopTalking;

  /** Click-to-talk (2026-09-03). One idempotent entry point so a double-click cannot start two
   * pipelines: `startTalking` already guards on `transmittingRef`/`startingTalkRef`, and routing
   * both directions through here means the component never has to reason about which state it is
   * in. Replaces the previous press-and-hold model, which depended on pointer-down/up pairs that
   * are unreliable on touch and unusable by keyboard. */
  function toggleTalking(): void {
    if (transmittingRef.current) {
      stopTalking();
      return;
    }
    void startTalking();
  }

  function computePhase(): IntercomPhase {
    if (startMutation.isPending) return "requesting";
    if (requestError) return requestError.unavailable ? "unavailable" : "error";
    if (!session) return "idle";
    if (manuallyStopped) return "stopped";
    // Bug 1 fix — takes priority over the player-state checks below: the relay's own close code
    // (read via the uplink socket's `onclose`, above) is a reliable, reason-bearing signal that
    // the backend session reached a terminal state, whether or not `player.state` (mpegts.js,
    // downlink-only) has caught up to a matching "closed"/"error" yet.
    if (terminalEvent) return terminalEvent.type;
    if (downlinkUrl === null) return "unavailable";
    if (player.state === "connected") return "connected";
    if (player.state === "error") return "error";
    // Fallback for the rare case the uplink socket's own close raced ahead of/behind this one,
    // or (pre-ADR-0036 callers, defensively) no uplink socket exists at all — still leaves
    // "connecting" reliably, never permanently stuck, just less specific than `terminalEvent`.
    if (player.state === "closed") return "unavailable";
    return "connecting";
  }

  const phase = computePhase();
  const canStart =
    deviceId !== null &&
    cameraId !== null &&
    phase !== "requesting" &&
    phase !== "connecting" &&
    phase !== "connected";
  const canStop = phase === "connecting" || phase === "connected";

  return {
    phase,
    requestError,
    terminalEvent,
    micError,
    isTransmitting,
    audioRef,
    micLevel,
    micSilent,
    micFailure,
    micUnavailable: micFailure !== null && MIC_FATAL_FAILURES.has(micFailure),
    micDeviceLabel,
    micDevices,
    selectedMicDeviceId,
    selectMicDevice,
    canStart,
    canStop,
    start,
    stop,
    startTalking,
    stopTalking,
    toggleTalking,
    talkSecondsRemaining,
    maxTalkSeconds: Math.round(MAX_TALK_DURATION_MS / 1000),
  };
}
