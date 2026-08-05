import { useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bell, Check } from "lucide-react";
import { usePageHeader } from "../../app/layout/PageHeaderContext";
import { Badge } from "../../shared/components/Badge/Badge";
import { Button } from "../../shared/components/Button/Button";
import { Card } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { FilterChips, type FilterChipOption } from "../../shared/components/Table/FilterChips";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../shared/components/Toast/toastStore";
import { useWebSocketChannel } from "../../shared/hooks/useWebSocket";
import { ApiError } from "../../shared/api/types";
import {
  listNotifications,
  markNotificationRead,
  type NotificationWsMessage,
} from "./api";
import { typeLabel, typeTone } from "./labels";
import { UNREAD_COUNT_QUERY_KEY } from "./useUnreadCount";
import styles from "./NotificationsPage.module.css";

const TYPE_FILTERS: FilterChipOption[] = [
  { id: "all", label: "All" },
  { id: "trip_started", label: "Trip Started", tone: "info" },
  { id: "approaching_stop", label: "Approaching Stop", tone: "warning" },
  { id: "arrived_org", label: "Arrived", tone: "success" },
  { id: "trip_completed", label: "Trip Completed", tone: "success" },
  { id: "subscription", label: "Subscription", tone: "purple" },
  { id: "system", label: "System", tone: "neutral" },
];

const PAGE_SIZE = 20;
const LIST_QUERY_KEY = ["notifications", "list"];

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * `/platform/notifications` + `/org/notifications` (F8) — one shared component, matching every
 * other phase's two-dashboard pattern (`.claude/rules/frontend.md` #1 note in `router.tsx`'s own
 * docstring). Unlike every other list page in this codebase, `GET /notifications` is scoped to
 * `recipient_user_id = principal.user_id`, not `organization_id` — this is **the signed-in
 * user's own personal inbox**, not a tenant-wide admin view; every role that can reach either
 * dashboard sees exactly the same shape, just their own rows.
 *
 * **First cursor-paginated page in this frontend** (`shared/api/listParams.ts`'s new
 * `CursorListParams`/`buildCursorListQuery`, `shared/api/types.ts`'s new `CursorPageWire`/
 * `toCursorPage`) — uses `@tanstack/react-query`'s `useInfiniteQuery` (already a dependency,
 * built for exactly this "Load more" shape) rather than hand-rolling page-number state, which
 * would not even fit this backend's cursor-only contract.
 *
 * **Live-updated over `/ws/notifications`** (`.claude/rules/frontend.md` #3) — subscribe is
 * implicit per API Contracts §11.3, so this just listens; a push invalidates the list (refetches
 * page one for real data) rather than splicing the WS frame's own partial fields into the cache,
 * since that frame deliberately carries no `status`/`read_at`/`data` (`NotificationWsMessage`'s
 * own docstring).
 */
export function NotificationsPage() {
  usePageHeader("Notifications", "Your own in-app notifications");
  const toast = useToast();
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState("all");

  const filters: Record<string, string> = typeFilter === "all" ? {} : { type: typeFilter };

  const query = useInfiniteQuery({
    queryKey: [...LIST_QUERY_KEY, typeFilter],
    queryFn: ({ pageParam }: { pageParam: string | null }) =>
      listNotifications({ limit: PAGE_SIZE, cursor: pageParam, filters }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => (lastPage.page.hasMore ? lastPage.page.nextCursor : undefined),
  });

  useWebSocketChannel<NotificationWsMessage>("/ws/notifications", {
    onMessage: (message) => {
      if (message.type === "notification") {
        void queryClient.invalidateQueries({ queryKey: LIST_QUERY_KEY });
        void queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_QUERY_KEY });
      }
    },
  });

  const markReadMutation = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LIST_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_QUERY_KEY });
    },
    onError: (error: unknown) => {
      toast.error(
        "Could not mark as read",
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.",
      );
    },
  });

  const notifications = query.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <div className={styles.page}>
      <FilterChips options={TYPE_FILTERS} activeId={typeFilter} onSelect={setTypeFilter} />

      {query.isError ? (
        <EmptyState
          icon={<Bell size={22} />}
          title="Could not load notifications"
          description={query.error instanceof ApiError ? query.error.message : "Something went wrong. Please try again."}
        />
      ) : query.isLoading ? (
        <div className={styles.list}>
          {Array.from({ length: 5 }, (_, i) => (
            <Card key={i} padded className={styles.row}>
              <Skeleton width="60%" height={15} />
              <Skeleton width="90%" height={13} />
            </Card>
          ))}
        </div>
      ) : notifications.length === 0 ? (
        <EmptyState
          icon={<Bell size={22} />}
          title="No notifications yet"
          description="Notifications about your trips, subscription, and the platform will appear here."
        />
      ) : (
        <>
          <ul className={styles.list}>
            {notifications.map((notification) => (
              <li key={notification.id}>
                <Card padded className={clsx(styles.row, notification.status === "unread" && styles.unread)}>
                  <div className={styles.rowHead}>
                    <Badge variant={typeTone(notification.type)} dot={notification.status === "unread"}>
                      {typeLabel(notification.type)}
                    </Badge>
                    <span className={styles.time}>{formatTimestamp(notification.createdAt)}</span>
                  </div>
                  <span className={styles.title}>{notification.title}</span>
                  <p className={styles.body}>{notification.body}</p>
                  {notification.status === "unread" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      leadingIcon={<Check size={14} />}
                      loading={markReadMutation.isPending && markReadMutation.variables === notification.id}
                      onClick={() => markReadMutation.mutate(notification.id)}
                    >
                      Mark as read
                    </Button>
                  )}
                </Card>
              </li>
            ))}
          </ul>

          {query.hasNextPage && (
            <Button variant="secondary" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
              Load more
            </Button>
          )}
        </>
      )}
    </div>
  );
}
