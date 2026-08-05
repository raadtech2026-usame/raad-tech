import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useWebSocketChannel } from "../../shared/hooks/useWebSocket";
import { listNotifications, type NotificationWsMessage } from "./api";

/** Shared across this hook and `NotificationsPage`'s own mark-read mutation, so marking
 * something read there immediately refreshes the bell badge here too — two independent
 * components agreeing on one cache entry rather than a second, hand-rolled cross-component
 * channel. */
export const UNREAD_COUNT_QUERY_KEY = ["notifications", "unread-count"];

/** No dedicated "unread count" endpoint exists — this counts `status === "unread"` among the
 * most recent 50 notifications (`GET /notifications`'s own max `limit`), which is exact for any
 * realistic inbox and only *undercounts* in the unlikely case of 50+ unread items sitting
 * unread at once; `IconButton`'s own badge already caps its displayed text at "9+", so that edge
 * case is invisible anyway. A real, disclosed limitation, not a fabricated total.
 *
 * Live-updated over `/ws/notifications` (`.claude/rules/frontend.md` #3: real-time data goes
 * over WebSocket, not REST polling) — every push is, by construction, a brand-new and therefore
 * unread notification, so this just invalidates the seed query rather than trying to merge a
 * partial WS frame into a running count by hand. This opens its own `/ws/notifications`
 * connection, independent of any `NotificationsPage` instance's own — `AppShell` renders on
 * every authenticated page, `NotificationsPage` only on one; sharing a single connection across
 * both would need a connection-scoped context provider this codebase doesn't have yet, a bigger
 * change than this widget warrants. */
export function useUnreadCount(): number {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: UNREAD_COUNT_QUERY_KEY,
    queryFn: async () => {
      const page = await listNotifications({ limit: 50, cursor: null, filters: {} });
      return page.data.filter((notification) => notification.status === "unread").length;
    },
    staleTime: 30_000,
  });

  useWebSocketChannel<NotificationWsMessage>("/ws/notifications", {
    onMessage: (message) => {
      if (message.type === "notification") {
        void queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_QUERY_KEY });
      }
    },
  });

  return query.data ?? 0;
}
