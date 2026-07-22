"""Unit tests for `modules.notifications.api.ws` — `/ws/notifications`'s connection lifecycle
(implicit subscribe to the caller's own stream) and broker-event fan-out. Stdlib `unittest` —
no `pytest` (not an approved dependency). Fakes are bound directly into a real `core.di.
container.Container`, the same convention `test_notification_subscribers.py`/
`test_tracking_ws.py` already establish.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import WebSocketDisconnect

from raad.core.di.container import Container
from raad.core.errors.exceptions import NotFoundError
from raad.core.events.base import DomainEvent
from raad.core.security.tokens import JwtTokenService, TokenService
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import SystemClock
from raad.interfaces.http.realtime import ConnectionManager, WsCloseCode
from raad.modules.notifications.api.ws import (
    build_notifications_fanout_handler,
    run_notifications_websocket,
)
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.queries import NotificationDTO
from raad.modules.notifications.application.services import NotificationApplicationService

ORG_ID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


class FakeNotificationService:
    def __init__(self, notifications_by_id: dict[str, NotificationDTO]) -> None:
        self._by_id = notifications_by_id

    async def get_notification_by_id(self, query, *, uow):
        notification = self._by_id.get(query.notification_id)
        if notification is None or notification.recipient_user_id != query.recipient_user_id:
            raise NotFoundError(f"Notification {query.notification_id} not found.")
        return notification


def make_container(notifications_by_id: dict[str, NotificationDTO] | None = None) -> Container:
    container = Container()
    container.bind_singleton(
        NotificationApplicationService, FakeNotificationService(notifications_by_id or {})
    )
    container.bind_singleton(NotificationsUnitOfWork, object())
    return container


def make_notification(
    *,
    notification_id: str = "notif-1",
    recipient_user_id: str = "user-1",
    type_: str = "trip_started",
    trip_id: str | None = "trip-1",
) -> NotificationDTO:
    return NotificationDTO(
        id=notification_id,
        organization_id=ORG_ID,
        recipient_user_id=recipient_user_id,
        type=type_,
        title="Morning trip started",
        body="Your child's bus has started its morning trip.",
        data=None,
        trip_id=trip_id,
        status="unread",
        created_at=datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc),
        read_at=None,
    )


def make_event(notification: NotificationDTO) -> DomainEvent:
    return DomainEvent(
        event_id="evt-1",
        event_type="NotificationCreated",
        version=1,
        occurred_at=notification.created_at,
        org_id=ORG_ID,
        correlation_id=None,
        payload={
            "recipient_user_id": notification.recipient_user_id,
            "type": notification.type,
            "trip_id": notification.trip_id,
            "actor_id": None,
        },
        aggregate_type="Notification",
        aggregate_id=notification.id,
    )


class FakeWebSocket:
    def __init__(self, *, messages: list[object] | None = None) -> None:
        self._messages = list(messages or [])
        self.sent: list[object] = []
        self.closed_with: int | None = None
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: object) -> None:
        self.sent.append(data)

    async def receive_json(self) -> object:
        if not self._messages:
            raise RuntimeError("no more fake messages queued")
        return self._messages.pop(0)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


class DisconnectingWebSocket(FakeWebSocket):
    async def receive_json(self) -> object:
        if not self._messages:
            raise WebSocketDisconnect(code=1000)
        return self._messages.pop(0)


def make_token_service() -> JwtTokenService:
    return JwtTokenService(
        secret_key="test-secret",
        algorithm="HS256",
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=1_209_600,
        clock=SystemClock(),
    )


class NotificationsFanoutHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_notification_created_forwards_frame_to_the_owning_recipient(self) -> None:
        notification = make_notification()
        container = make_container({notification.id: notification})
        connections = ConnectionManager()
        websocket = FakeWebSocket()
        principal = Principal(user_id="user-1", role=Role.PARENT, org_id=ORG_ID)
        await connections.register("user-1", websocket, principal)
        handler = build_notifications_fanout_handler(connections=connections, container=container)

        await handler(make_event(notification))

        self.assertEqual(len(websocket.sent), 1)
        frame = websocket.sent[0]
        self.assertEqual(frame["type"], "notification")
        self.assertEqual(frame["id"], "notif-1")
        self.assertEqual(frame["category"], "trip_started")
        self.assertEqual(frame["title"], "Morning trip started")
        self.assertEqual(frame["trip_id"], "trip-1")

    async def test_no_subscribers_for_recipient_is_a_no_op(self) -> None:
        notification = make_notification()
        container = make_container({notification.id: notification})
        handler = build_notifications_fanout_handler(
            connections=ConnectionManager(), container=container
        )
        await handler(make_event(notification))  # must not raise

    async def test_missing_notification_row_is_a_no_op_not_a_crash(self) -> None:
        """The event names a notification id the application service can't find (ownership
        mismatch or already-gone row) — must degrade quietly, never propagate and kill the
        fan-out worker's whole tick for every *other* event."""
        container = make_container({})  # nothing registered
        connections = ConnectionManager()
        websocket = FakeWebSocket()
        await connections.register(
            "user-1", websocket, Principal(user_id="user-1", role=Role.PARENT, org_id=ORG_ID)
        )
        handler = build_notifications_fanout_handler(connections=connections, container=container)

        await handler(make_event(make_notification()))

        self.assertEqual(websocket.sent, [])

    async def test_unrelated_event_type_is_ignored(self) -> None:
        connections = ConnectionManager()
        websocket = FakeWebSocket()
        await connections.register(
            "user-1", websocket, Principal(user_id="user-1", role=Role.PARENT, org_id=ORG_ID)
        )
        handler = build_notifications_fanout_handler(
            connections=connections, container=make_container()
        )

        await handler(
            DomainEvent(
                event_id="evt-2",
                event_type="TripStarted",
                version=1,
                occurred_at=SystemClock().now(),
                org_id=ORG_ID,
                correlation_id=None,
                payload={"recipient_user_id": "user-1"},
                aggregate_type="Trip",
                aggregate_id="trip-1",
            )
        )

        self.assertEqual(websocket.sent, [])


class RunNotificationsWebsocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_happy_path_authenticates_registers_and_cleans_up_on_disconnect(
        self,
    ) -> None:
        token_service = make_token_service()
        pair = token_service.issue_token_pair(subject="user-1", role=Role.PARENT, org_id=ORG_ID)
        container = make_container()
        container.bind_singleton(TokenService, token_service)
        connections = ConnectionManager()
        websocket = DisconnectingWebSocket(
            messages=[{"type": "auth", "token": pair.access_token}]
        )

        await run_notifications_websocket(
            websocket,
            container=container,
            connections=connections,
            auth_frame_timeout_seconds=5.0,
        )

        self.assertTrue(websocket.accepted)
        self.assertEqual(await connections.subscribers_for("user-1"), [])  # cleaned up

    async def test_no_token_service_bound_closes_unauthenticated(self) -> None:
        container = make_container()
        websocket = FakeWebSocket()

        await run_notifications_websocket(
            websocket,
            container=container,
            connections=ConnectionManager(),
            auth_frame_timeout_seconds=5.0,
        )

        self.assertEqual(websocket.closed_with, WsCloseCode.UNAUTHENTICATED)

    async def test_invalid_auth_frame_closes_unauthenticated(self) -> None:
        container = make_container()
        container.bind_singleton(TokenService, make_token_service())
        websocket = FakeWebSocket(messages=[{"type": "auth", "token": "garbage"}])

        await run_notifications_websocket(
            websocket,
            container=container,
            connections=ConnectionManager(),
            auth_frame_timeout_seconds=5.0,
        )

        self.assertEqual(websocket.closed_with, WsCloseCode.UNAUTHENTICATED)

    async def test_connection_stays_open_and_registered_until_disconnect(self) -> None:
        """Unlike the happy-path test above (which disconnects immediately after auth), this
        connection has a second, ignorable frame queued — proving the connection stays
        registered and open across multiple `receive_json()` calls, not just a single
        auth-then-immediately-gone cycle."""
        token_service = make_token_service()
        pair = token_service.issue_token_pair(subject="user-42", role=Role.PARENT, org_id=ORG_ID)
        container = make_container()
        container.bind_singleton(TokenService, token_service)
        connections = ConnectionManager()
        seen_during_connection: list[int] = []

        class ObservingWebSocket(DisconnectingWebSocket):
            async def receive_json(self):
                if self._messages == [{"type": "ignored"}]:
                    seen_during_connection.append(
                        len(await connections.subscribers_for("user-42"))
                    )
                return await super().receive_json()

        websocket = ObservingWebSocket(
            messages=[{"type": "auth", "token": pair.access_token}, {"type": "ignored"}]
        )

        await run_notifications_websocket(
            websocket,
            container=container,
            connections=connections,
            auth_frame_timeout_seconds=5.0,
        )

        self.assertEqual(seen_during_connection, [1])
        self.assertEqual(await connections.subscribers_for("user-42"), [])


if __name__ == "__main__":
    unittest.main()
