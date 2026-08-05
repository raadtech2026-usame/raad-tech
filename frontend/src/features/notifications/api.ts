import { apiRequest } from "../../shared/api/client";
import { buildCursorListQuery, type CursorListParams } from "../../shared/api/listParams";
import { toCursorPage, type CursorPage, type CursorPageWire } from "../../shared/api/types";

/** `notifications.domain.value_objects.NotificationType` (Database Design §7.5, matching API
 * Contracts §13.3's notification catalogue). `subscription`/`system` are documented values with
 * no current auto-trigger anywhere in this codebase (CLAUDE.md's own Notifications section) —
 * still real, legal values a row can carry, so still handled here, not omitted. */
export type NotificationType =
  | "trip_started"
  | "approaching_stop"
  | "arrived_org"
  | "trip_completed"
  | "subscription"
  | "system";

/** `notifications.domain.value_objects.NotificationStatus` — derived from `read_at`, not a
 * persisted column (`infra/repositories.py`'s own docstring: not filterable for exactly this
 * reason). */
export type NotificationStatus = "unread" | "read";

/** `NotificationResponse` (`notifications/api/schemas.py`) — the full row shape, returned by
 * both the list and get-by-id routes (unlike `Trip`/`Route`, there is no separate thin "summary"
 * shape here, so a list page never needs a second per-row detail fetch). */
export interface Notification {
  id: string;
  organizationId: string;
  recipientUserId: string;
  type: NotificationType;
  title: string;
  body: string;
  data: Record<string, unknown> | null;
  tripId: string | null;
  status: NotificationStatus;
  createdAt: string;
  readAt: string | null;
}

interface NotificationWire {
  id: string;
  organization_id: string;
  recipient_user_id: string;
  type: string;
  title: string;
  body: string;
  data: Record<string, unknown> | null;
  trip_id: string | null;
  status: string;
  created_at: string;
  read_at: string | null;
}

function toNotification(wire: NotificationWire): Notification {
  return {
    id: wire.id,
    organizationId: wire.organization_id,
    recipientUserId: wire.recipient_user_id,
    type: wire.type as NotificationType,
    title: wire.title,
    body: wire.body,
    data: wire.data,
    tripId: wire.trip_id,
    status: wire.status as NotificationStatus,
    createdAt: wire.created_at,
    readAt: wire.read_at,
  };
}

/** `GET /notifications` — **the caller's own notifications only** (`recipient_user_id =
 * principal.user_id`, enforced server-side): the first list endpoint in this codebase scoped by
 * personal ownership rather than tenant/`organization_id`. Cursor-paginated, newest-first,
 * `?filter[type]=...` is the only supported filter (`status` is domain-derived, not filterable —
 * see `NotificationStatus`'s own docstring). */
export async function listNotifications(params: CursorListParams): Promise<CursorPage<Notification>> {
  const wire = await apiRequest<CursorPageWire<NotificationWire>>(`/notifications?${buildCursorListQuery(params)}`);
  return toCursorPage(wire, toNotification);
}

/** `POST /notifications/{id}/read` — idempotent (`domain/entities.py`'s `Notification.mark_read`);
 * ownership-enforced server-side (a non-owner id raises `NotFoundError`, 404, not 403 — see that
 * route's own docstring). */
export async function markNotificationRead(id: string): Promise<Notification> {
  const wire = await apiRequest<NotificationWire>(`/notifications/${id}/read`, { method: "POST" });
  return toNotification(wire);
}

/** `/ws/notifications`'s one server->client frame shape (API Contracts §11.3,
 * `notifications/api/ws.py`'s own `_notification_frame`). Subscribe is implicit — no frame this
 * app needs to send, unlike `/ws/tracking`. Deliberately thin: no `status`/`read_at`/
 * `organization_id`/`data` (the frame only ever represents a brand-new, thus unread, notification)
 * — a live push refetches the real list/count from `GET /notifications` rather than constructing
 * a partial `Notification` from these few fields, so nothing here is ever treated as the full row. */
export interface NotificationWsMessage {
  type: "notification";
  id: string;
  category: string;
  title: string;
  body: string;
  trip_id: string | null;
  created_at: string;
}
