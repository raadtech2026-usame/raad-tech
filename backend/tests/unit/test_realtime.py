"""Unit tests for `interfaces.http.realtime` — the shared WebSocket infrastructure
`/ws/tracking` and `/ws/notifications` both build on (`ConnectionManager`,
`authenticate_connection`, `BrokerFanOutWorker`, `safe_close`). Stdlib `unittest` — no
`pytest` (not an approved dependency). Fakes are plain duck-typed classes, matching this
codebase's established `test_notification_subscribers.py`/`test_policy_guards.py` convention;
`FakeConnection` implements exactly `RealtimeConnection`'s Protocol shape
(`send_json`/`receive_json`/`close`) with no FastAPI/Starlette dependency at all.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from raad.core.events.base import DomainEvent
from raad.core.security.tokens import JwtTokenService
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.interfaces.http.realtime import (
    BrokerFanOutWorker,
    ConnectionManager,
    authenticate_connection,
    safe_close,
)

ORG_ID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def make_token_service(clock: Clock) -> JwtTokenService:
    return JwtTokenService(
        secret_key="test-secret",
        algorithm="HS256",
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=1_209_600,
        clock=clock,
    )


class FakeConnection:
    """Implements `RealtimeConnection`'s Protocol shape only — no FastAPI/Starlette type in
    sight, proving `ConnectionManager`/`authenticate_connection` are genuinely decoupled from
    the real transport (Ports & Adapters)."""

    def __init__(self, *, messages: list[object] | None = None) -> None:
        self._messages = list(messages or [])
        self.sent: list[object] = []
        self.closed_with: int | None = None

    async def send_json(self, data: object) -> None:
        self.sent.append(data)

    async def receive_json(self) -> object:
        if not self._messages:
            raise RuntimeError("no more fake messages queued")
        return self._messages.pop(0)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


class RaisingCloseConnection(FakeConnection):
    async def close(self, code: int = 1000) -> None:
        raise RuntimeError("already closed on the wire")


def make_principal(user_id: str = "user-1", role: Role = Role.PARENT) -> Principal:
    return Principal(user_id=user_id, role=role, org_id=ORG_ID)


class ConnectionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_then_subscribers_for_returns_the_connection_and_principal(self) -> None:
        manager = ConnectionManager()
        connection = FakeConnection()
        principal = make_principal()

        await manager.register("veh-1", connection, principal)
        subscribers = await manager.subscribers_for("veh-1")

        self.assertEqual(subscribers, [(connection, principal)])

    async def test_subscribers_for_unknown_key_returns_empty_list(self) -> None:
        manager = ConnectionManager()
        self.assertEqual(await manager.subscribers_for("nope"), [])

    async def test_unregister_removes_only_that_connection(self) -> None:
        manager = ConnectionManager()
        a, b = FakeConnection(), FakeConnection()
        principal = make_principal()
        await manager.register("veh-1", a, principal)
        await manager.register("veh-1", b, principal)

        await manager.unregister("veh-1", a)

        subscribers = await manager.subscribers_for("veh-1")
        self.assertEqual(subscribers, [(b, principal)])

    async def test_unregister_last_connection_for_a_key_drops_the_key_entirely(self) -> None:
        manager = ConnectionManager()
        connection = FakeConnection()
        await manager.register("veh-1", connection, make_principal())

        await manager.unregister("veh-1", connection)

        self.assertEqual(await manager.connection_count(), 0)

    async def test_unregister_unknown_key_is_a_safe_no_op(self) -> None:
        manager = ConnectionManager()
        await manager.unregister("never-registered", FakeConnection())  # must not raise

    async def test_two_keys_are_independent(self) -> None:
        manager = ConnectionManager()
        a, b = FakeConnection(), FakeConnection()
        await manager.register("veh-1", a, make_principal("p1"))
        await manager.register("veh-2", b, make_principal("p2"))

        self.assertEqual(len(await manager.subscribers_for("veh-1")), 1)
        self.assertEqual(len(await manager.subscribers_for("veh-2")), 1)
        self.assertEqual(await manager.connection_count(), 2)

    async def test_concurrent_registration_of_many_connections_is_safe(self) -> None:
        """Multiple concurrent clients (task's own explicit requirement) — registering 50
        connections concurrently under the same key must not lose any of them to a race on the
        internal dict, proving the `asyncio.Lock` guard actually does its job."""
        manager = ConnectionManager()
        connections = [FakeConnection() for _ in range(50)]
        principal = make_principal()

        await asyncio.gather(
            *(manager.register("veh-1", c, principal) for c in connections)
        )

        self.assertEqual(await manager.connection_count(), 50)


class AuthenticateConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_auth_frame_resolves_principal(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        pair = service.issue_token_pair(subject="user-1", role=Role.PARENT, org_id=ORG_ID)
        connection = FakeConnection(messages=[{"type": "auth", "token": pair.access_token}])

        principal = await authenticate_connection(
            connection, token_service=service, timeout_seconds=5.0
        )

        self.assertEqual(principal, Principal(user_id="user-1", role=Role.PARENT, org_id=ORG_ID))

    async def test_missing_type_field_returns_none(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        connection = FakeConnection(messages=[{"token": "irrelevant"}])

        self.assertIsNone(
            await authenticate_connection(connection, token_service=service, timeout_seconds=5.0)
        )

    async def test_wrong_frame_type_returns_none(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        connection = FakeConnection(messages=[{"type": "subscribe", "channel": "vehicle"}])

        self.assertIsNone(
            await authenticate_connection(connection, token_service=service, timeout_seconds=5.0)
        )

    async def test_non_string_token_returns_none(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        connection = FakeConnection(messages=[{"type": "auth", "token": 12345}])

        self.assertIsNone(
            await authenticate_connection(connection, token_service=service, timeout_seconds=5.0)
        )

    async def test_invalid_token_returns_none(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        connection = FakeConnection(messages=[{"type": "auth", "token": "garbage"}])

        self.assertIsNone(
            await authenticate_connection(connection, token_service=service, timeout_seconds=5.0)
        )

    async def test_timeout_waiting_for_first_frame_returns_none(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)

        class NeverSendsConnection(FakeConnection):
            async def receive_json(self) -> object:
                await asyncio.sleep(10)  # longer than the timeout below
                raise AssertionError("should have timed out first")

        connection = NeverSendsConnection()

        principal = await authenticate_connection(
            connection, token_service=service, timeout_seconds=0.05
        )
        self.assertIsNone(principal)


class SafeCloseTests(unittest.IsolatedAsyncioTestCase):
    async def test_closes_with_the_given_code(self) -> None:
        connection = FakeConnection()
        await safe_close(connection, 4403)
        self.assertEqual(connection.closed_with, 4403)

    async def test_swallows_close_errors(self) -> None:
        connection = RaisingCloseConnection()
        await safe_close(connection, 4403)  # must not raise


class FakeBrokerConsumer:
    def __init__(self, events: list[DomainEvent]) -> None:
        self._events = events

    async def consume(self, handler) -> None:
        for event in self._events:
            await handler(event)


class BrokerFanOutWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_dispatches_every_consumed_event_to_the_handler(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        events = [
            DomainEvent(
                event_id=f"evt-{i}",
                event_type="DevicePositionReported",
                version=1,
                occurred_at=clock.now(),
                org_id=ORG_ID,
                correlation_id=None,
                payload={"vehicle_id": "veh-1"},
                aggregate_type="Vehicle",
                aggregate_id="veh-1",
            )
            for i in range(3)
        ]
        received: list[DomainEvent] = []

        async def handler(event: DomainEvent) -> None:
            received.append(event)

        worker = BrokerFanOutWorker(
            "test-fanout", clock=clock, consumer=FakeBrokerConsumer(events), handler=handler
        )
        await worker.run_once()

        self.assertEqual(received, events)

    async def test_a_failing_tick_is_recorded_but_does_not_raise(self) -> None:
        """Mirrors `core.workers.base.Worker._tick`'s own "a single bad tick never kills the
        loop" contract — exercised here via the public `start`/`stop` lifecycle rather than
        reaching into the private `_tick` method."""
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))

        class FailingConsumer:
            async def consume(self, handler) -> None:
                raise RuntimeError("redis unreachable")

        worker = BrokerFanOutWorker(
            "test-fanout", clock=clock, consumer=FailingConsumer(), handler=lambda e: None
        )
        await worker.start(interval_seconds=0.01)
        await asyncio.sleep(0.05)
        await worker.stop()

        health = worker.health()
        self.assertIsNotNone(health.last_error)
        self.assertIn("redis unreachable", health.last_error)


if __name__ == "__main__":
    unittest.main()
