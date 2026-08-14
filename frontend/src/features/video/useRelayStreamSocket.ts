import { useEffect, useRef, useState } from "react";

/**
 * A minimal, feature-local WebSocket connector for the JT1078 relay's own viewer endpoint
 * (`services/jt1078/src/viewer/viewer_server.py`) — deliberately **not** `shared/hooks/
 * useWebSocket.useWebSocketChannel`, which is hardcoded to this backend's own `env.wsBaseUrl`-
 * relative `/ws/*` namespace, this app's own bearer-token auth-frame handshake, and JSON-only
 * `event.data` parsing. The relay is a different host entirely (`streamUrl` is already a
 * fully-qualified `ws://.../viewer?token=...` URL returned by `POST /video/live`), performs no
 * app-level authentication of its own (the signed token is already in the query string —
 * `ViewerServer._authorize`), and sends raw binary FLV bytes, never JSON
 * (`SessionBroadcastHub.add_viewer`/`broadcast_video`).
 *
 * **No auto-reconnect, deliberately** — unlike `useWebSocketChannel`. The relay's viewer token is
 * single-use (`session/viewer_token.SingleUseTokenGuard.claim`, one successful claim ever); a
 * second connection attempt with the same `streamUrl` would be rejected with close code `4001`
 * (`invalid_token`), not gracefully retried. A dropped connection means the caller must request a
 * fresh session (a new `stream_url`), not that this hook should silently retry the stale one.
 *
 * **Does not decode or render FLV** — this hook only proves *relay-side connectivity*: the socket
 * opened, and at least one binary frame has been received (the relay always sends the FLV file
 * header immediately on a successful `add_viewer`, before any real device frame necessarily has —
 * see `VideoPage.tsx`'s own module docstring for why `"connected"` is deliberately not called
 * `"live"` or `"playing"`). Actually decoding/rendering those bytes into a `<video>` element needs
 * an FLV-over-WebSocket demuxer (e.g. `flv.js`, itself primarily built for HTTP-FLV — a WS source
 * needs a custom loader), which is a new frontend dependency not yet approved
 * (`.claude/rules/workflow.md` #1/#2) — deliberately not added speculatively here.
 */

export type RelayStreamState = "idle" | "connecting" | "connected" | "closed" | "error";

export interface UseRelayStreamSocketResult {
  state: RelayStreamState;
  /** The WebSocket close event's own `code` (e.g. `4001` invalid/expired/already-used token,
   * `4004` `session_not_active` — `ViewerServer._handle_connection`'s own close codes) — `null`
   * until a close has actually happened. */
  closeCode: number | null;
  /** Running total of binary bytes received since connecting — a real, live-updating proof the
   * relay is actually sending data, not a fabricated progress indicator. Resets to 0 whenever
   * `streamUrl` changes. */
  bytesReceived: number;
}

export function useRelayStreamSocket(streamUrl: string | null): UseRelayStreamSocketResult {
  const [state, setState] = useState<RelayStreamState>("idle");
  const [closeCode, setCloseCode] = useState<number | null>(null);
  const [bytesReceived, setBytesReceived] = useState(0);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    setCloseCode(null);
    setBytesReceived(0);

    if (!streamUrl) {
      setState("idle");
      return;
    }

    setState("connecting");
    const socket = new WebSocket(streamUrl);
    socket.binaryType = "arraybuffer";
    socketRef.current = socket;

    socket.addEventListener("message", (event: MessageEvent<ArrayBuffer | string>) => {
      const size =
        typeof event.data === "string" ? event.data.length : event.data.byteLength;
      setBytesReceived((total) => total + size);
      setState((current) => (current === "connecting" ? "connected" : current));
    });

    socket.addEventListener("close", (event: CloseEvent) => {
      setCloseCode(event.code);
      setState("closed");
    });

    socket.addEventListener("error", () => {
      setState("error");
    });

    return () => {
      socketRef.current = null;
      socket.close();
    };
  }, [streamUrl]);

  return { state, closeCode, bytesReceived };
}
