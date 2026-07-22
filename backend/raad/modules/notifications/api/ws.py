"""Realtime WebSocket surface for `notifications` (`/ws/notifications`, API Contracts
§11.1/§11.3; Backend LLD §16.1/§16.2). Mounted by `interfaces/http/ws.py`, the same
aggregation shape §16.1 already establishes for REST (`notifications_router` in
`interfaces/http/api_v1.py`).

**Auth model — identical to `tracking.api.ws`**: first `auth` frame, verified by
`interfaces/http/realtime.authenticate_connection` — the **one** shared implementation this
module and `tracking.api.ws` both call (never a per-module copy), which in turn calls
`core.security.tokens.resolve_principal_from_access_token`, the same function
`SecurityContextMiddleware` uses for HTTP requests.

**Subscribe: implicit** (API Contracts §11.3: "Subscribe: implicit to the authenticated user's
own stream") — no `subscribe` frame is expected; the connection is registered under
`principal.user_id` immediately once authenticated, and stays registered for its whole
lifetime (unlike `tracking`, there is only ever one "channel" per connection here).

**No CR-1 re-check here — deliberately, not an oversight.** `SubscriptionAccessPolicy` (CR-1)
is already enforced *upstream*, at `Notification` creation time, by the (separate-process)
Notification Worker (`modules/notifications/events/subscribers.py`'s `_NotificationFanOut`):
a denied Parent-Pays parent simply never gets a `Notification` row created for a transport
event in the first place (`domain/policies.py`'s own module docstring: "the withholding
decision belongs to the... Notification Worker"). By the time a `NotificationCreated` event
reaches this channel's fan-out handler, CR-1 has already run. Re-deriving it a second time
here would duplicate an already-enforced decision, not add safety. What this handler *does*
check — cheaply, as a belt-and-suspenders ownership guard — is that the event's own
`recipient_user_id` matches the connection's own authenticated `principal.user_id`, mirroring
`GET /notifications`'s identical personal-ownership scoping (the first list endpoint in this
codebase scoped that way, `notifications.application.queries` module docstring).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from raad.core.di.container import Container
from raad.core.errors.exceptions import NotFoundError
from raad.core.events.base import DomainEvent
from raad.core.security.tokens import TokenService
from raad.interfaces.http.realtime import (
    ConnectionManager,
    WsCloseCode,
    authenticate_connection,
    safe_close,
)
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.queries import (
    GetNotificationByIdQuery,
    NotificationDTO,
)
from raad.modules.notifications.application.services import NotificationApplicationService

notifications_ws_router = APIRouter()

NOTIFICATION_CREATED_EVENT_TYPE = "NotificationCreated"


def _notification_frame(notification: NotificationDTO) -> dict[str, Any]:
    """API Contracts §11.3's documented server->client frame. `category` is the wire name the
    WebSocket contract uses for what REST's `NotificationResponse` calls `type` — sourced from
    the same `Notification.type` field, just a different field name at this one documented
    surface (flagged, not silently reconciled — no document names these as the same field)."""
    return {
        "type": "notification",
        "id": notification.id,
        "category": notification.type,
        "title": notification.title,
        "body": notification.body,
        "trip_id": notification.trip_id,
        "created_at": notification.created_at.isoformat(),
    }


async def _handle_notification_created_event(
    event: DomainEvent,
    *,
    connections: ConnectionManager,
    container: Container,
) -> None:
    recipient_user_id = event.payload.get("recipient_user_id")
    if not recipient_user_id:
        return
    subscribers = await connections.subscribers_for(recipient_user_id)
    if not subscribers:
        return

    notification_service = container.resolve(NotificationApplicationService)
    uow = container.resolve(NotificationsUnitOfWork)
    try:
        notification = await notification_service.get_notification_by_id(
            GetNotificationByIdQuery(
                notification_id=event.aggregate_id, recipient_user_id=recipient_user_id
            ),
            uow=uow,
        )
    except NotFoundError:
        # Ownership mismatch between the event's own payload and the row it names, or the row
        # is already gone — either way, nothing safe to forward.
        return

    frame = _notification_frame(notification)
    for connection, principal in subscribers:
        if principal.user_id != recipient_user_id:
            # Belt-and-suspenders only (see module docstring) - the registry is already keyed
            # by user_id, so this should never actually be false.
            continue
        try:
            await connection.send_json(frame)
        except Exception:  # noqa: BLE001 - one broken subscriber must not block the rest
            await connections.unregister(recipient_user_id, connection)
            await safe_close(connection, WsCloseCode.BAD_REQUEST)


def build_notifications_fanout_handler(
    *, connections: ConnectionManager, container: Container
) -> Callable[[DomainEvent], Awaitable[None]]:
    """The handler `BrokerFanOutWorker` dispatches every consumed event to — only reacts to
    `NotificationCreated`; every other event on the shared stream is ignored (still acked, see
    `tracking.api.ws.build_tracking_fanout_handler`'s identical note)."""

    async def handler(event: DomainEvent) -> None:
        if event.event_type == NOTIFICATION_CREATED_EVENT_TYPE:
            await _handle_notification_created_event(
                event, connections=connections, container=container
            )

    return handler


async def run_notifications_websocket(
    websocket: WebSocket,
    *,
    container: Container,
    connections: ConnectionManager,
    auth_frame_timeout_seconds: float,
) -> None:
    """Connection lifecycle: accept -> authenticate -> register (implicit subscribe) -> idle
    until disconnect -> clean up. Unlike `tracking`, there is no subscribe/message protocol to
    loop on after auth — the connection just needs to stay open so `receive_json()` can detect
    a client-initiated close; any frame the client actually sends is ignored (this channel is
    server->client only, API Contracts §11.3)."""
    await websocket.accept()

    token_service = container.try_resolve(TokenService)
    if token_service is None:
        await websocket.close(code=WsCloseCode.UNAUTHENTICATED)
        return

    principal = await authenticate_connection(
        websocket, token_service=token_service, timeout_seconds=auth_frame_timeout_seconds
    )
    if principal is None:
        await websocket.close(code=WsCloseCode.UNAUTHENTICATED)
        return

    await connections.register(principal.user_id, websocket, principal)
    try:
        while True:
            await websocket.receive_json()  # ignored - see docstring
    except WebSocketDisconnect:
        pass
    finally:
        await connections.unregister(principal.user_id, websocket)


@notifications_ws_router.websocket("")
async def notifications_websocket(websocket: WebSocket) -> None:
    container: Container = websocket.app.state.container
    connections: ConnectionManager = websocket.app.state.notifications_connections
    settings = websocket.app.state.settings
    await run_notifications_websocket(
        websocket,
        container=container,
        connections=connections,
        auth_frame_timeout_seconds=settings.websocket.auth_frame_timeout_seconds,
    )


__all__ = [
    "notifications_ws_router",
    "build_notifications_fanout_handler",
    "run_notifications_websocket",
]
