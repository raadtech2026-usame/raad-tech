import { useEffect, useRef, useState } from "react";
import { env } from "../../config/env";
import { useAuthStore } from "../stores/authStore";

export type WebSocketStatus = "connecting" | "open" | "closed";

/** Mirrors `backend/raad/interfaces/http/realtime.WsCloseCode` — a client-side close on one
 * of these means retrying with the *same* token is pointless (no auto-reconnect below). */
const UNAUTHENTICATED_CLOSE_CODE = 4401;
const FORBIDDEN_CLOSE_CODE = 4403;
const RECONNECT_DELAY_MS = 2000;

interface UseWebSocketChannelOptions<T> {
  /** Set to `false` to tear the connection down (e.g. the feature using it isn't mounted, or
   * the user isn't authenticated yet) without unmounting the calling component. */
  enabled?: boolean;
  onMessage: (message: T) => void;
}

interface UseWebSocketChannelResult {
  status: WebSocketStatus;
  lastCloseCode: number | null;
}

/**
 * One realtime channel connection (`/ws/tracking` or `/ws/notifications`), matching API
 * Contracts §11.1's documented protocol: connect, send `{"type":"auth","token":...}` as the
 * first frame, then read/write JSON frames. Auto-reconnects on a transient close (network
 * blip, server restart) after `RECONNECT_DELAY_MS`, but **not** on `UNAUTHENTICATED`/
 * `FORBIDDEN` — those mean the current token is invalid/expired or the caller isn't
 * authorized, and blindly retrying with the same token would just spin forever
 * (`.claude/rules/flutter.md` #6's "never fail silently" principle applied to the web
 * dashboard too: a stuck reconnect loop with no visible indicator would be exactly that).
 * Subscribe (`/ws/tracking`'s own `{"type":"subscribe",...}` frame) is each feature's own
 * concern, sent via the returned `send` — not hardcoded into this generic hook.
 */
export function useWebSocketChannel<T>(
  path: string,
  options: UseWebSocketChannelOptions<T>,
): UseWebSocketChannelResult & { send: (message: unknown) => void } {
  const { enabled = true, onMessage } = options;
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const socketRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<WebSocketStatus>("connecting");
  const [lastCloseCode, setLastCloseCode] = useState<number | null>(null);

  useEffect(() => {
    if (!enabled) {
      setStatus("closed");
      return;
    }

    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect(): void {
      const accessToken = useAuthStore.getState().accessToken;
      if (!accessToken) {
        setStatus("closed");
        return;
      }

      setStatus("connecting");
      const socket = new WebSocket(`${env.wsBaseUrl}${path}`);
      socketRef.current = socket;

      socket.addEventListener("open", () => {
        socket.send(JSON.stringify({ type: "auth", token: accessToken }));
        setStatus("open");
      });

      socket.addEventListener("message", (event: MessageEvent<string>) => {
        try {
          onMessageRef.current(JSON.parse(event.data) as T);
        } catch {
          // Malformed frame - ignored, mirroring the backend's own "ignore unknown message
          // shapes" posture rather than crashing the UI over one bad frame.
        }
      });

      socket.addEventListener("close", (event: CloseEvent) => {
        setStatus("closed");
        setLastCloseCode(event.code);
        const isAuthOrPolicyClose =
          event.code === UNAUTHENTICATED_CLOSE_CODE || event.code === FORBIDDEN_CLOSE_CODE;
        if (!cancelled && !isAuthOrPolicyClose) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      });

      socket.addEventListener("error", () => {
        socket.close();
      });
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [path, enabled]);

  function send(message: unknown): void {
    socketRef.current?.send(JSON.stringify(message));
  }

  return { status, lastCloseCode, send };
}
