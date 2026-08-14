import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRelayStreamSocket } from "./useRelayStreamSocket";

type Listener = (event: { data?: unknown; code?: number }) => void;

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readonly url: string;
  binaryType = "blob";
  closed = false;
  private listeners: Record<string, Listener[]> = {};

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, callback: Listener): void {
    (this.listeners[type] ??= []).push(callback);
  }

  close(): void {
    this.closed = true;
  }

  emitMessage(data: unknown): void {
    this.listeners.message?.forEach((cb) => cb({ data }));
  }

  emitClose(code: number): void {
    this.listeners.close?.forEach((cb) => cb({ code }));
  }

  emitError(): void {
    this.listeners.error?.forEach((cb) => cb({}));
  }
}

const STREAM_URL = "ws://jt1078-relay:7911/viewer?token=abc123";

describe("useRelayStreamSocket", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("stays idle and opens no socket when streamUrl is null", () => {
    const { result } = renderHook(() => useRelayStreamSocket(null));

    expect(result.current).toEqual({ state: "idle", closeCode: null, bytesReceived: 0 });
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("opens a binary-mode socket to the given streamUrl and starts connecting", () => {
    const { result } = renderHook(() => useRelayStreamSocket(STREAM_URL));

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toBe(STREAM_URL);
    expect(FakeWebSocket.instances[0].binaryType).toBe("arraybuffer");
    expect(result.current.state).toBe("connecting");
  });

  it("transitions to connected on the first binary frame and accumulates bytes received", () => {
    const { result } = renderHook(() => useRelayStreamSocket(STREAM_URL));
    const socket = FakeWebSocket.instances[0];

    act(() => socket.emitMessage(new ArrayBuffer(13)));
    expect(result.current.state).toBe("connected");
    expect(result.current.bytesReceived).toBe(13);

    act(() => socket.emitMessage(new ArrayBuffer(7)));
    expect(result.current.state).toBe("connected");
    expect(result.current.bytesReceived).toBe(20);
  });

  it("records the close code on close (e.g. 4004 session_not_active)", () => {
    const { result } = renderHook(() => useRelayStreamSocket(STREAM_URL));
    const socket = FakeWebSocket.instances[0];

    act(() => socket.emitClose(4004));

    expect(result.current.state).toBe("closed");
    expect(result.current.closeCode).toBe(4004);
  });

  it("transitions to error on a socket error event", () => {
    const { result } = renderHook(() => useRelayStreamSocket(STREAM_URL));
    const socket = FakeWebSocket.instances[0];

    act(() => socket.emitError());

    expect(result.current.state).toBe("error");
  });

  it("closes the old socket and resets state/bytes when streamUrl changes", () => {
    const { result, rerender } = renderHook(({ url }) => useRelayStreamSocket(url), {
      initialProps: { url: STREAM_URL },
    });
    const firstSocket = FakeWebSocket.instances[0];
    act(() => firstSocket.emitMessage(new ArrayBuffer(5)));
    expect(result.current.bytesReceived).toBe(5);

    rerender({ url: "ws://jt1078-relay:7911/viewer?token=different" });

    expect(firstSocket.closed).toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(result.current).toEqual({ state: "connecting", closeCode: null, bytesReceived: 0 });
  });

  it("closes the socket on unmount", () => {
    const { unmount } = renderHook(() => useRelayStreamSocket(STREAM_URL));
    const socket = FakeWebSocket.instances[0];

    unmount();

    expect(socket.closed).toBe(true);
  });

  it("never auto-reconnects after a close — the relay's viewer token is single-use", () => {
    renderHook(() => useRelayStreamSocket(STREAM_URL));
    const socket = FakeWebSocket.instances[0];

    act(() => socket.emitClose(1000));

    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
