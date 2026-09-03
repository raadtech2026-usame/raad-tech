import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("./api", () => ({
  requestIntercom: vi.fn(),
  stopVideoSession: vi.fn(),
}));

const playerReturn: { state: string; errorMessage: string | null } = {
  state: "idle",
  errorMessage: null,
};
vi.mock("./useMpegtsPlayer", () => ({
  useMpegtsPlayer: () => playerReturn,
}));

import { requestIntercom, stopVideoSession } from "./api";
import { useIntercomController } from "./useIntercomController";

/** Bug 1 regression coverage — the relay closes the uplink socket with a distinguishable code
 * (`4010` FAILED / `4011` ENDED, `services/jt1078/src/relay.py._on_session_removed`) the instant
 * the backend session becomes terminal. A real `WebSocket` against a fake `ws://relay/...` URL
 * can't be driven deterministically in jsdom, so every test in this file gets this controllable
 * stand-in instead — `simulateServerClose` fires `onclose` directly, mirroring a server-sent close
 * frame without requiring the test to first call `.close()` itself (which is what a *client*-
 * initiated close, e.g. `teardownUplinkSocket`, does). */
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  // Real `WebSocket`'s own static ready-state constants - the hook's `onaudioprocess` guard
  // (`socket.readyState !== WebSocket.OPEN`) reads the *stubbed global* `WebSocket.OPEN`, so this
  // double must define it too, not just an instance-level numeric convention.
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  binaryType = "";
  // Opens synchronously for this test double's purposes - real WebSocket handshakes are
  // asynchronous, but nothing in this file drives that timing, and the mic-capture regression
  // test below needs a send-ready socket immediately after construction.
  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: (() => void) | null = null;

  /** Bug 2 regression coverage — every frame this hook ever sends over the uplink socket,
   * captured here (rather than discarded) so tests can assert on real frame sizes/counts. */
  sentFrames: Uint8Array[] = [];

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  close(code = 1000, reason = ""): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }

  send(data: Uint8Array): void {
    this.sentFrames.push(data);
  }

  simulateServerClose(code: number, reason: string): void {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
}

const SESSION = {
  id: "session-1",
  organizationId: "org-1",
  deviceId: "device-1",
  cameraId: "camera-1",
  purpose: "intercom" as const,
  requestedBy: "user-1",
  windowStart: null,
  windowEnd: null,
  status: "requested" as const,
  startedAt: null,
  endedAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  streamUrl: "ws://relay/viewer?token=viewer-abc",
  uplinkUrl: "ws://relay/viewer?token=uplink-abc",
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useIntercomController", () => {
  beforeEach(() => {
    vi.mocked(requestIntercom).mockReset();
    vi.mocked(stopVideoSession).mockReset().mockResolvedValue({ ...SESSION, status: "ended" });
    playerReturn.state = "idle";
    playerReturn.errorMessage = null;
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("cannot start while either id is null", () => {
    const { result } = renderHook(() => useIntercomController(null, "camera-1"), { wrapper });
    expect(result.current.canStart).toBe(false);
    expect(result.current.phase).toBe("idle");
  });

  it("requests an intercom session with exactly the given device/camera ids", async () => {
    vi.mocked(requestIntercom).mockImplementation(() => new Promise(() => {}));
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });

    act(() => result.current.start());

    await waitFor(() => expect(result.current.phase).toBe("requesting"));
    expect(requestIntercom).toHaveBeenCalledWith("device-1", "camera-1");
  });

  it("reaches 'connected' once the session exists and the player reports connected", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });

    act(() => result.current.start());

    await waitFor(() => expect(result.current.phase).toBe("connected"));
    expect(result.current.canStop).toBe(true);
    expect(result.current.isTransmitting).toBe(false);
  });

  it("classifies a 409 (device already has an open intercom session) distinctly", async () => {
    const apiErrorModule = await import("../../shared/api/types");
    vi.mocked(requestIntercom).mockRejectedValue(
      new apiErrorModule.ApiError(409, { code: "CONFLICT", message: "in use", correlationId: null }),
    );
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });

    act(() => result.current.start());

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.requestError?.alreadyInUse).toBe(true);
    expect(result.current.requestError?.unavailable).toBe(false);
  });

  it("maps a 500 to 'unavailable' rather than a generic error", async () => {
    const apiErrorModule = await import("../../shared/api/types");
    vi.mocked(requestIntercom).mockRejectedValue(
      new apiErrorModule.ApiError(500, { code: "INTERNAL_ERROR", message: "boom", correlationId: null }),
    );
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });

    act(() => result.current.start());

    await waitFor(() => expect(result.current.phase).toBe("unavailable"));
    expect(result.current.requestError?.alreadyInUse).toBe(false);
  });

  it("stop() calls stopVideoSession and resets the phase", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("connected"));

    await act(() => result.current.stop());

    expect(stopVideoSession).toHaveBeenCalledWith("session-1", undefined);
    expect(result.current.phase).toBe("stopped");
    expect(result.current.isTransmitting).toBe(false);
  });

  it("startTalking without microphone/Web Audio support sets micError, never crashes", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("connected"));

    await act(() => result.current.startTalking());

    expect(result.current.isTransmitting).toBe(false);
    expect(result.current.micError).not.toBeNull();
  });

  describe("Bug 2 regression — uplink packetization end to end (mic capture -> WebSocket)", () => {
    /** Minimal Web Audio doubles - jsdom implements none of this natively. Mirrors exactly the
     * calls `useIntercomController.startTalking` actually makes (`createMediaStreamSource`,
     * `createScriptProcessor`, `createGain`, `.connect`/`.disconnect`) so `onaudioprocess` can be
     * invoked directly from the test, the same way the browser would invoke it per audio
     * callback. `capturedProcessor` (module-scoped, reset each test) is how the test gets a
     * handle on the exact instance the hook wired `onaudioprocess` onto. */
    class FakeAudioNode {
      connect(): void {}
      disconnect(): void {}
    }
    type OnAudioProcess = (event: { inputBuffer: { getChannelData(i: number): Float32Array } }) => void;
    class FakeScriptProcessorNode extends FakeAudioNode {
      onaudioprocess: OnAudioProcess | null = null;
    }
    class FakeGainNode extends FakeAudioNode {
      gain = { value: 1 };
    }
    let capturedProcessor: FakeScriptProcessorNode | null = null;
    // Bug 3 regression coverage - every processor/context this fake ever constructs, so a test
    // can assert exactly one pipeline was ever built across multiple Hold-to-Talk presses.
    let capturedProcessors: FakeScriptProcessorNode[] = [];
    let audioContextCloseCalls = 0;
    class FakeAudioContext {
      sampleRate: number;
      state: "running" | "suspended" | "closed" = "running";
      destination = new FakeAudioNode();
      constructor(options?: { sampleRate?: number }) {
        // Mirrors a real browser that *does* honor the requested rate (Chrome/Edge, per this
        // hook's own docstring) - keeps `resampleFloat32Linear` a no-op so this test's expected
        // frame math (2048 bytes in -> six 320-byte frames + 128-byte remainder) is exact.
        this.sampleRate = options?.sampleRate ?? 8000;
      }
      createMediaStreamSource(): FakeAudioNode {
        return new FakeAudioNode();
      }
      createScriptProcessor(): FakeScriptProcessorNode {
        capturedProcessor = new FakeScriptProcessorNode();
        capturedProcessors.push(capturedProcessor);
        return capturedProcessor;
      }
      createGain(): FakeGainNode {
        return new FakeGainNode();
      }
      async resume(): Promise<void> {
        this.state = "running";
      }
      async close(): Promise<void> {
        this.state = "closed";
        audioContextCloseCalls += 1;
      }
    }

    let getUserMediaMock: ReturnType<typeof vi.fn>;
    beforeEach(() => {
      capturedProcessor = null;
      capturedProcessors = [];
      audioContextCloseCalls = 0;
      getUserMediaMock = vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
        // Real `MediaStream`s expose this; the hook reads it for the mic-device label shown
        // beside the Talk button (2026-09-03).
        getAudioTracks: () => [{ label: "Test Microphone", stop: vi.fn() }],
      });
      vi.stubGlobal("AudioContext", FakeAudioContext);
      vi.stubGlobal("navigator", {
        mediaDevices: { getUserMedia: getUserMediaMock },
      });
    });

    it("chunks one 2048-sample capture callback into <=950-byte frames - never the raw 2048-byte payload that used to break MalformedExtendedRtpFrameError", async () => {
      vi.mocked(requestIntercom).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));

      await act(() => result.current.startTalking());
      expect(result.current.isTransmitting).toBe(true);
      expect(capturedProcessor).not.toBeNull();

      const uplinkSocket = MockWebSocket.instances[MockWebSocket.instances.length - 1];

      // Drive one real capture callback with a 2048-sample buffer, exactly the shape that
      // previously produced one 2048-byte WebSocket message.
      act(() => {
        capturedProcessor?.onaudioprocess?.({
          inputBuffer: { getChannelData: () => new Float32Array(2048) },
        });
      });

      expect(uplinkSocket.sentFrames.length).toBe(6); // 2048 / 320 = 6 full frames + remainder
      for (const frame of uplinkSocket.sentFrames) {
        expect(frame.length).toBeLessThanOrEqual(950); // the actual JT/T 1078 protocol ceiling
        expect(frame.length).toBe(320); // ADR-0033's own confirmed device frame size
      }
    });

    it("flushes the leftover partial frame on stopTalking() rather than dropping it", async () => {
      vi.mocked(requestIntercom).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));

      await act(() => result.current.startTalking());
      const uplinkSocket = MockWebSocket.instances[MockWebSocket.instances.length - 1];

      act(() => {
        capturedProcessor?.onaudioprocess?.({
          inputBuffer: { getChannelData: () => new Float32Array(2048) },
        });
      });
      expect(uplinkSocket.sentFrames.length).toBe(6);

      act(() => result.current.stopTalking());

      // The 128-byte remainder from the 2048-sample callback (2048 - 6*320 = 128) is flushed as
      // one final, short-but-valid frame rather than silently discarded.
      expect(uplinkSocket.sentFrames.length).toBe(7);
      expect(uplinkSocket.sentFrames[6].length).toBe(128);
    });

    it("Bug 3 regression: a second Hold-to-Talk press reuses the existing pipeline instead of building a duplicate one", async () => {
      vi.mocked(requestIntercom).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));

      await act(() => result.current.startTalking());
      expect(getUserMediaMock).toHaveBeenCalledTimes(1);
      expect(capturedProcessors.length).toBe(1);
      const firstProcessor = capturedProcessors[0];

      act(() => result.current.stopTalking());
      expect(result.current.isTransmitting).toBe(false);

      // A second press - the historical bug built a second, independent AudioContext/
      // ScriptProcessorNode here, leaving the first one still running and both writing into the
      // same shared uplink chunker concurrently (the confirmed root cause of "spoken word
      // repeats several times" on any press after the first).
      await act(() => result.current.startTalking());

      expect(getUserMediaMock).toHaveBeenCalledTimes(1); // still just once - no new pipeline
      expect(capturedProcessors.length).toBe(1); // no second ScriptProcessorNode was ever built
      expect(capturedProcessor).toBe(firstProcessor); // the exact same node is still in use
      expect(result.current.isTransmitting).toBe(true);
    });

    it("Bug 3 regression: only the reused pipeline's frames reach the uplink socket on a second press - no duplicated/interleaved audio", async () => {
      vi.mocked(requestIntercom).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));

      await act(() => result.current.startTalking());
      const uplinkSocket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
      const firstProcessor = capturedProcessor;
      act(() => {
        firstProcessor?.onaudioprocess?.({
          inputBuffer: { getChannelData: () => new Float32Array(320) },
        });
      });
      act(() => result.current.stopTalking());
      const framesAfterFirstPress = uplinkSocket.sentFrames.length;

      await act(() => result.current.startTalking());
      // If a second, orphaned pipeline existed (the historical bug), *its* stale
      // `onaudioprocess` closure would still be live too - simulating a callback on it directly
      // proves there is no such second, independent processor to call in the first place, since
      // `capturedProcessor`/`capturedProcessors` only ever recorded one.
      expect(capturedProcessors.length).toBe(1);
      act(() => {
        capturedProcessor?.onaudioprocess?.({
          inputBuffer: { getChannelData: () => new Float32Array(320) },
        });
      });

      // Exactly one new frame from this one, single capture call - not two (which a duplicated,
      // concurrently-writing pipeline would have produced).
      expect(uplinkSocket.sentFrames.length).toBe(framesAfterFirstPress + 1);
    });

    it("Bug 3 regression: teardownMic (stop()) still fully releases the pipeline - a fresh session builds a genuinely new one", async () => {
      vi.mocked(requestIntercom).mockResolvedValue(SESSION);
      vi.mocked(stopVideoSession).mockResolvedValue({ ...SESSION, status: "ended" });
      playerReturn.state = "connected";
      const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));

      await act(() => result.current.startTalking());
      expect(capturedProcessors.length).toBe(1);

      await act(() => result.current.stop());
      expect(audioContextCloseCalls).toBe(1); // the full pipeline was actually released

      act(() => result.current.start());
      await waitFor(() => expect(result.current.phase).toBe("connected"));
      await act(() => result.current.startTalking());

      // A genuinely new session gets a genuinely new pipeline (not an attempt to reuse a closed,
      // released one) - `getUserMedia` called again, a second, independent processor built.
      expect(getUserMediaMock).toHaveBeenCalledTimes(2);
      expect(capturedProcessors.length).toBe(2);
    });
  });

  it("reaches 'failed' and surfaces the reason when the relay closes the uplink socket with code 4010", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("connected"));

    const uplinkSocket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => uplinkSocket.simulateServerClose(4010, "ingest_timeout"));

    await waitFor(() => expect(result.current.phase).toBe("failed"));
    expect(result.current.terminalEvent).toEqual({ type: "failed", reason: "ingest_timeout" });
    // Not stuck showing "connecting"/"connected" any more, and Talk/Stop are no longer offered.
    expect(result.current.canStop).toBe(false);
    expect(result.current.canStart).toBe(true);
  });

  it("reaches 'ended' (distinct from 'failed') when the relay closes the uplink socket with code 4011", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("connected"));

    const uplinkSocket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => uplinkSocket.simulateServerClose(4011, "business_api_requested"));

    await waitFor(() => expect(result.current.phase).toBe("ended"));
    expect(result.current.terminalEvent).toEqual({
      type: "ended",
      reason: "business_api_requested",
    });
  });

  it("reaches 'failed' from REQUESTED (still connecting) too, not only once already connected", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connecting"; // never reached "connected" - the exact stuck scenario
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("connecting"));

    const uplinkSocket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => uplinkSocket.simulateServerClose(4010, "ingest_timeout"));

    await waitFor(() => expect(result.current.phase).toBe("failed"));
  });

  it("an operator-initiated stop is unaffected by the same close handling (ordinary code 1000)", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result } = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("connected"));

    await act(() => result.current.stop());

    expect(result.current.phase).toBe("stopped");
    expect(result.current.terminalEvent).toBeNull();
  });

  it("resets the session when deviceId/cameraId change, abandoning the previous session", async () => {
    vi.mocked(requestIntercom).mockResolvedValue(SESSION);
    playerReturn.state = "connected";
    const { result, rerender } = renderHook(
      ({ deviceId }: { deviceId: string }) => useIntercomController(deviceId, "camera-1"),
      { wrapper, initialProps: { deviceId: "device-1" } },
    );
    act(() => result.current.start());
    await waitFor(() => expect(result.current.phase).toBe("connected"));

    rerender({ deviceId: "device-2" });

    await waitFor(() => expect(result.current.phase).toBe("idle"));
    // The unmount cleanup path passes `keepalive: true` (ADR-0037) - distinct from an explicit
    // Stop button click, which does not (asserted separately, `stop()`'s own test above).
    expect(stopVideoSession).toHaveBeenCalledWith("session-1", { keepalive: true });
  });

  describe("microphone metering and device selection (2026-09-03)", () => {
    // Live incident: Chromium selected a virtual "Voice Changer" input that produced exact
    // zeros. Every layer reported success and correctly-framed packets reached the MDVR, but the
    // driver heard nothing and the operator had no way to tell. These cover the feedback that
    // makes that visible, plus the picker that lets them switch away from it.
    class Node2 {
      connect(): void {}
      disconnect(): void {}
    }
    type OnProc = (event: { inputBuffer: { getChannelData(i: number): Float32Array } }) => void;
    class Proc2 extends Node2 {
      onaudioprocess: OnProc | null = null;
    }
    let processor: Proc2 | null = null;
    class Ctx2 {
      sampleRate = 8000; // keeps resampling a no-op so the level math is exact
      state = "running";
      destination = new Node2();
      createMediaStreamSource(): Node2 { return new Node2(); }
      createScriptProcessor(): Proc2 { processor = new Proc2(); return processor; }
      createGain() { return Object.assign(new Node2(), { gain: { value: 1 } }); }
      async resume(): Promise<void> {}
      async close(): Promise<void> {}
    }

    let getUserMediaMock: ReturnType<typeof vi.fn>;
    let enumerateMock: ReturnType<typeof vi.fn>;

    beforeEach(() => {
      processor = null;
      getUserMediaMock = vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
        getAudioTracks: () => [{ label: "Voice Changer Virtual Audio Device", stop: vi.fn() }],
      });
      enumerateMock = vi.fn().mockResolvedValue([
        { kind: "audioinput", deviceId: "real-mic", label: "Headset Microphone" },
        { kind: "audioinput", deviceId: "virtual", label: "Voice Changer Virtual Audio Device" },
        { kind: "videoinput", deviceId: "cam", label: "Webcam" },
      ]);
      vi.stubGlobal("AudioContext", Ctx2);
      vi.stubGlobal("navigator", {
        mediaDevices: { getUserMedia: getUserMediaMock, enumerateDevices: enumerateMock },
      });
    });

    async function connectAndTalk() {
      vi.mocked(requestIntercom).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const view = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
      act(() => view.result.current.start());
      await waitFor(() => expect(view.result.current.phase).toBe("connected"));
      await act(() => view.result.current.startTalking());
      return view;
    }

    function drive(samples: Float32Array, times = 1) {
      for (let n = 0; n < times; n += 1) {
        act(() => {
          processor?.onaudioprocess?.({ inputBuffer: { getChannelData: () => samples } });
        });
      }
    }

    const tone = () => {
      const buf = new Float32Array(2048);
      for (let i = 0; i < buf.length; i += 1) buf[i] = Math.sin(i / 4) * 0.5;
      return buf;
    };

    it("exposes the device label actually in use", async () => {
      const { result } = await connectAndTalk();
      expect(result.current.micDeviceLabel).toBe("Voice Changer Virtual Audio Device");
    });

    it("lists only audio inputs for the picker", async () => {
      const { result } = await connectAndTalk();
      await waitFor(() => expect(result.current.micDevices.length).toBe(2));
      expect(result.current.micDevices.map((d) => d.deviceId)).toEqual(["real-mic", "virtual"]);
    });

    it("selecting a device requests that exact input on the next press", async () => {
      const { result } = await connectAndTalk();
      act(() => result.current.selectMicDevice("real-mic"));
      await act(() => result.current.startTalking());
      const last = getUserMediaMock.mock.calls.at(-1)![0] as { audio: Record<string, unknown> };
      expect(last.audio.deviceId).toEqual({ exact: "real-mic" });
    });

    it("selecting a device tears the old pipeline down so the change takes effect", async () => {
      // `startTalking` deliberately reuses a live pipeline (Bug 3 fix), so without an explicit
      // teardown a device change would silently not apply until the session ended.
      const { result } = await connectAndTalk();
      expect(getUserMediaMock).toHaveBeenCalledTimes(1);
      act(() => result.current.selectMicDevice("real-mic"));
      await act(() => result.current.startTalking());
      expect(getUserMediaMock).toHaveBeenCalledTimes(2);
    });

    it("reports a level above zero for real audio", async () => {
      const { result } = await connectAndTalk();
      drive(tone(), 3);
      await waitFor(() => expect(result.current.micLevel).toBeGreaterThan(0.01));
      expect(result.current.micSilent).toBe(false);
    });

    it("flags a silent microphone after the warning delay", async () => {
      const { result } = await connectAndTalk();
      drive(new Float32Array(2048), 3); // exact zeros - the virtual-device failure mode
      await waitFor(() => expect(result.current.micSilent).toBe(true), { timeout: 4000 });
      expect(result.current.micLevel).toBeLessThan(0.0015);
    });

    it("clears the silence flag once real audio arrives", async () => {
      const { result } = await connectAndTalk();
      drive(new Float32Array(2048), 3);
      await waitFor(() => expect(result.current.micSilent).toBe(true), { timeout: 4000 });
      drive(tone(), 3);
      await waitFor(() => expect(result.current.micSilent).toBe(false));
    });
  });

  describe("Option C — microphone device lifecycle (2026-09-03)", () => {
    class N3 { connect(): void {} disconnect(): void {} }
    type OnProc3 = (e: { inputBuffer: { getChannelData(i: number): Float32Array } }) => void;
    class P3 extends N3 { onaudioprocess: OnProc3 | null = null; }
    class C3 {
      sampleRate = 8000;
      state = "running";
      destination = new N3();
      createMediaStreamSource(): N3 { return new N3(); }
      createScriptProcessor(): P3 { return new P3(); }
      createGain() { return Object.assign(new N3(), { gain: { value: 1 } }); }
      async resume(): Promise<void> {}
      async close(): Promise<void> {}
    }
    const stream = () => ({
      getTracks: () => [{ stop: vi.fn() }],
      getAudioTracks: () => [{ label: "Built-in Microphone", stop: vi.fn() }],
    });
    const domError = (name: string) => Object.assign(new Error(name), { name });

    let gum: ReturnType<typeof vi.fn>;
    let enumerate: ReturnType<typeof vi.fn>;
    let listeners: Record<string, Array<() => void>>;

    beforeEach(() => {
      listeners = {};
      gum = vi.fn().mockResolvedValue(stream());
      enumerate = vi.fn().mockResolvedValue([
        { kind: "audioinput", deviceId: "mic-a", label: "Built-in Microphone" },
        { kind: "audioinput", deviceId: "mic-b", label: "USB Headset" },
      ]);
      vi.stubGlobal("AudioContext", C3);
      vi.stubGlobal("navigator", {
        mediaDevices: {
          getUserMedia: gum,
          enumerateDevices: enumerate,
          addEventListener: (t: string, h: () => void) => { (listeners[t] ??= []).push(h); },
          removeEventListener: (t: string, h: () => void) => {
            listeners[t] = (listeners[t] ?? []).filter((x) => x !== h);
          },
        },
      });
    });

    async function connected() {
      vi.mocked(requestIntercom).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const view = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
      act(() => view.result.current.start());
      await waitFor(() => expect(view.result.current.phase).toBe("connected"));
      return view;
    }

    it("normal operation requests a GENERIC microphone with no deviceId", async () => {
      const { result } = await connected();
      await act(() => result.current.startTalking());
      const constraints = gum.mock.calls[0][0] as { audio: Record<string, unknown> };
      expect(constraints.audio).not.toHaveProperty("deviceId");
      expect(result.current.selectedMicDeviceId).toBeNull();
    });

    it("never sends a deviceId to the backend", async () => {
      const { result } = await connected();
      await act(() => result.current.startTalking());
      act(() => result.current.selectMicDevice("mic-b"));
      await act(() => result.current.startTalking());
      const calls = vi.mocked(requestIntercom).mock.calls;
      expect(calls.every((c) => !JSON.stringify(c).includes("mic-b"))).toBe(true);
    });

    it("NotAllowedError -> permission denied, Talk disabled, no retry loop", async () => {
      gum.mockRejectedValue(domError("NotAllowedError"));
      const { result } = await connected();
      await act(() => result.current.startTalking());
      expect(result.current.micFailure).toBe("permission-denied");
      expect(result.current.micUnavailable).toBe(true);
      expect(result.current.micError).toMatch(/address bar/i);
      expect(gum).toHaveBeenCalledTimes(1);
    });

    it("NotFoundError -> no device, Talk disabled", async () => {
      gum.mockRejectedValue(domError("NotFoundError"));
      const { result } = await connected();
      await act(() => result.current.startTalking());
      expect(result.current.micFailure).toBe("no-device");
      expect(result.current.micUnavailable).toBe(true);
    });

    it("NotReadableError -> device busy, Talk stays available to retry", async () => {
      gum.mockRejectedValue(domError("NotReadableError"));
      const { result } = await connected();
      await act(() => result.current.startTalking());
      expect(result.current.micFailure).toBe("device-busy");
      expect(result.current.micUnavailable).toBe(false);
      expect(result.current.micError).toMatch(/another application/i);
    });

    it("AbortError is classified distinctly", async () => {
      gum.mockRejectedValue(domError("AbortError"));
      const { result } = await connected();
      await act(() => result.current.startTalking());
      expect(result.current.micFailure).toBe("aborted");
    });

    it("OverconstrainedError falls back to System Default and keeps intercom working", async () => {
      const { result } = await connected();
      act(() => result.current.selectMicDevice("mic-b"));
      gum.mockReset();
      gum.mockRejectedValueOnce(domError("OverconstrainedError")).mockResolvedValue(stream());

      await act(() => result.current.startTalking());

      const first = gum.mock.calls[0][0] as { audio: Record<string, unknown> };
      const second = gum.mock.calls[1][0] as { audio: Record<string, unknown> };
      expect(first.audio.deviceId).toEqual({ exact: "mic-b" });
      expect(second.audio).not.toHaveProperty("deviceId");
      expect(result.current.selectedMicDeviceId).toBeNull();
      expect(result.current.isTransmitting).toBe(true);
    });

    it("devicechange refreshes the input list", async () => {
      const { result } = await connected();
      await act(() => result.current.startTalking());
      enumerate.mockResolvedValue([
        { kind: "audioinput", deviceId: "mic-a", label: "Built-in Microphone" },
        { kind: "audioinput", deviceId: "mic-c", label: "Bluetooth Headset" },
      ]);
      await act(async () => { listeners.devicechange?.forEach((h) => h()); });
      await waitFor(() =>
        expect(result.current.micDevices.map((d) => d.deviceId)).toEqual(["mic-a", "mic-c"]),
      );
    });

    it("an unplugged SELECTED device falls back to System Default", async () => {
      const { result } = await connected();
      await act(() => result.current.startTalking());
      act(() => result.current.selectMicDevice("mic-b"));
      enumerate.mockResolvedValue([
        { kind: "audioinput", deviceId: "mic-a", label: "Built-in Microphone" },
      ]);

      await act(async () => { listeners.devicechange?.forEach((h) => h()); });

      await waitFor(() => expect(result.current.selectedMicDeviceId).toBeNull());
      expect(result.current.micFailure).toBe("device-gone");
    });

    it("devicechange never guesses a replacement device by name", async () => {
      const { result } = await connected();
      await act(() => result.current.startTalking());
      act(() => result.current.selectMicDevice("mic-b"));
      enumerate.mockResolvedValue([
        { kind: "audioinput", deviceId: "mic-z", label: "USB Headset" },
      ]);

      await act(async () => { listeners.devicechange?.forEach((h) => h()); });

      await waitFor(() => expect(result.current.selectedMicDeviceId).toBeNull());
      expect(result.current.selectedMicDeviceId).not.toBe("mic-z");
    });

    it("a device change while transmitting does not build a duplicate pipeline", async () => {
      const { result } = await connected();
      await act(() => result.current.startTalking());
      act(() => result.current.selectMicDevice("mic-b"));
      gum.mockClear();
      enumerate.mockResolvedValue([
        { kind: "audioinput", deviceId: "mic-a", label: "Built-in Microphone" },
      ]);

      await act(async () => { listeners.devicechange?.forEach((h) => h()); });
      await waitFor(() => expect(result.current.selectedMicDeviceId).toBeNull());

      expect(gum.mock.calls.length).toBeLessThanOrEqual(1);
    });

    it("removes the devicechange listener on unmount", async () => {
      const { unmount } = await connected();
      expect(listeners.devicechange?.length).toBe(1);
      unmount();
      expect(listeners.devicechange?.length ?? 0).toBe(0);
    });
  });

  describe("click-to-talk with a 10s hard stop (2026-09-03)", () => {
    class N4 { connect(): void {} disconnect(): void {} }
    type OnProc4 = (e: { inputBuffer: { getChannelData(i: number): Float32Array } }) => void;
    class P4 extends N4 { onaudioprocess: OnProc4 | null = null; }
    let contexts4 = 0;
    let processors4: P4[] = [];
    class C4 {
      sampleRate = 8000;
      state = "running";
      destination = new N4();
      constructor() { contexts4 += 1; }
      createMediaStreamSource(): N4 { return new N4(); }
      createScriptProcessor(): P4 { const p = new P4(); processors4.push(p); return p; }
      createGain() { return Object.assign(new N4(), { gain: { value: 1 } }); }
      async resume(): Promise<void> {}
      async close(): Promise<void> {}
    }
    let gum4: ReturnType<typeof vi.fn>;

    beforeEach(() => {
      contexts4 = 0;
      processors4 = [];
      gum4 = vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
        getAudioTracks: () => [{ label: "Built-in Microphone", stop: vi.fn() }],
      });
      vi.stubGlobal("AudioContext", C4);
      vi.stubGlobal("navigator", {
        mediaDevices: {
          getUserMedia: gum4,
          enumerateDevices: vi.fn().mockResolvedValue([]),
          addEventListener: () => {},
          removeEventListener: () => {},
        },
      });
    });

    async function connected() {
      vi.mocked(requestIntercom).mockResolvedValue(SESSION);
      playerReturn.state = "connected";
      const view = renderHook(() => useIntercomController("device-1", "camera-1"), { wrapper });
      act(() => view.result.current.start());
      await waitFor(() => expect(view.result.current.phase).toBe("connected"));
      return view;
    }

    it("a single toggle starts transmission — no hold required", async () => {
      const { result } = await connected();
      await act(async () => { result.current.toggleTalking(); });
      await waitFor(() => expect(result.current.isTransmitting).toBe(true));
      expect(gum4).toHaveBeenCalledTimes(1);
    });

    it("requests a generic microphone with no deviceId", async () => {
      const { result } = await connected();
      await act(async () => { result.current.toggleTalking(); });
      await waitFor(() => expect(result.current.isTransmitting).toBe(true));
      const constraints = gum4.mock.calls[0][0] as { audio: Record<string, unknown> };
      expect(constraints.audio).not.toHaveProperty("deviceId");
    });

    it("a second toggle stops transmission immediately", async () => {
      const { result } = await connected();
      await act(async () => { result.current.toggleTalking(); });
      await waitFor(() => expect(result.current.isTransmitting).toBe(true));

      await act(async () => { result.current.toggleTalking(); });

      expect(result.current.isTransmitting).toBe(false);
    });

    it("stops automatically after the 10 second maximum", async () => {
      // `shouldAdvanceTime` lets the fake clock track real time so `waitFor` still resolves, while
      // `advanceTimersByTime` below still drives the 10s hard stop deterministically.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const { result } = await connected();
        await act(async () => { result.current.toggleTalking(); });
        await waitFor(() => expect(result.current.isTransmitting).toBe(true));

        await act(async () => { vi.advanceTimersByTime(9000); });
        expect(result.current.isTransmitting).toBe(true);

        await act(async () => { vi.advanceTimersByTime(1200); });
        expect(result.current.isTransmitting).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it("the hard stop needs no further user action and leaves no armed timer", async () => {
      // `shouldAdvanceTime` lets the fake clock track real time so `waitFor` still resolves, while
      // `advanceTimersByTime` below still drives the 10s hard stop deterministically.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const { result } = await connected();
        await act(async () => { result.current.toggleTalking(); });
        await waitFor(() => expect(result.current.isTransmitting).toBe(true));
        await act(async () => { vi.advanceTimersByTime(10500); });
        expect(result.current.isTransmitting).toBe(false);
        expect(result.current.talkSecondsRemaining).toBe(0);

        // Advancing far past the window must not toggle anything back on.
        await act(async () => { vi.advanceTimersByTime(30000); });
        expect(result.current.isTransmitting).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it("a manual stop disarms the timer so it cannot fire on the next transmission", async () => {
      // `shouldAdvanceTime` lets the fake clock track real time so `waitFor` still resolves, while
      // `advanceTimersByTime` below still drives the 10s hard stop deterministically.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const { result } = await connected();
        await act(async () => { result.current.toggleTalking(); });
        await waitFor(() => expect(result.current.isTransmitting).toBe(true));
        await act(async () => { vi.advanceTimersByTime(3000); });
        await act(async () => { result.current.toggleTalking(); });  // manual stop at 3s
        expect(result.current.isTransmitting).toBe(false);

        await act(async () => { result.current.toggleTalking(); });  // start again
        await waitFor(() => expect(result.current.isTransmitting).toBe(true));
        // The first transmission's remaining 7s must not stop this new one.
        await act(async () => { vi.advanceTimersByTime(7500); });
        expect(result.current.isTransmitting).toBe(true);
      } finally {
        vi.useRealTimers();
      }
    });

    it("rapid double activation never builds a duplicate pipeline", async () => {
      const { result } = await connected();
      await act(async () => {
        result.current.toggleTalking();
        result.current.toggleTalking();
      });
      await waitFor(() => expect(result.current.isTransmitting).toBe(true));
      expect(gum4).toHaveBeenCalledTimes(1);
      expect(contexts4).toBe(1);
      expect(processors4.length).toBe(1);
    });

    it("exposes the countdown and the ceiling for display", async () => {
      const { result } = await connected();
      expect(result.current.maxTalkSeconds).toBe(10);
      await act(async () => { result.current.toggleTalking(); });
      await waitFor(() => expect(result.current.isTransmitting).toBe(true));
      expect(result.current.talkSecondsRemaining).toBeGreaterThan(0);
      expect(result.current.talkSecondsRemaining).toBeLessThanOrEqual(10);
    });

    it("ending the session while talking clears the timer and stops transmitting", async () => {
      // `shouldAdvanceTime` lets the fake clock track real time so `waitFor` still resolves, while
      // `advanceTimersByTime` below still drives the 10s hard stop deterministically.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const { result } = await connected();
        await act(async () => { result.current.toggleTalking(); });
        await waitFor(() => expect(result.current.isTransmitting).toBe(true));

        await act(async () => { await result.current.stop(); });

        expect(result.current.isTransmitting).toBe(false);
        expect(result.current.talkSecondsRemaining).toBe(0);
        await act(async () => { vi.advanceTimersByTime(20000); });
        expect(result.current.isTransmitting).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it("unmounting while talking leaves no orphan timer", async () => {
      // `shouldAdvanceTime` lets the fake clock track real time so `waitFor` still resolves, while
      // `advanceTimersByTime` below still drives the 10s hard stop deterministically.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const { result, unmount } = await connected();
        await act(async () => { result.current.toggleTalking(); });
        await waitFor(() => expect(result.current.isTransmitting).toBe(true));
        unmount();
        // Must not throw on a torn-down hook.
        await act(async () => { vi.advanceTimersByTime(20000); });
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
