"""Realtime WebSocket infrastructure shared by `/ws/tracking` and `/ws/notifications` (API
Contracts §11; Backend LLD §16.1/§16.2). Lives in `interfaces/http/`, not any single
bounded-context module — the same placement `policy_guards.py`/`pagination.py` already
establish for cross-cutting HTTP-layer infrastructure that no single module owns.

**Why a new in-process consumer per channel, not the existing `BrokerConsumer` binding.**
`core/di/bootstrap.py` binds exactly one `BrokerConsumer` (`group_name="notification-worker"`),
consumed only by the separate `workers/bootstrap.py` process's `NotificationWorker` — a
different OS process from the one serving these WebSocket connections (`interfaces/workers/
bootstrap.py`'s own module docstring: "Entry point: `python -m raad.interfaces.workers.
bootstrap`"). A worker process cannot push onto a WebSocket held open by the API process's own
event loop — the only thing they share is Redis. So each realtime channel gets its **own**
`RedisStreamsBrokerConsumer` (own consumer group, e.g. `ws-tracking`/`ws-notifications`) —
reusing the exact same class ADR-0008 already established, on the same `raad:events` stream,
just a distinct logical consumer group, the same "one instance per logical worker/consumer
group" shape that class's own docstring already documents. Constructed with its own fresh
`Redis.from_url(...)` client, mirroring `core/di/bootstrap.py`'s own precedent of using a
separate client per logical consumer even though they usually point at the same instance.

**Ports & Adapters.** `ConnectionManager` depends only on `RealtimeConnection` (a `Protocol` —
`send_json`/`close`), never on `starlette.websockets.WebSocket` directly, so it is testable with
a plain fake and could, in principle, be swapped for a different transport without touching
call sites. `BrokerFanOutWorker` wraps one `BrokerConsumer` + one handler in the exact
`core.workers.base.Worker` lifecycle (start/stop/health) `NotificationWorker` already
establishes — the same start/stop/error-isolation shape, reused rather than reinvented.

**Deployment-shape caveat, flagged rather than silently assumed** (mirrors `core.workers.
idempotency.InMemoryIdempotencyStore`'s own identical caveat): `ConnectionManager` is an
in-memory, single-process registry. It correctly supports many concurrent WebSocket clients
within one API server process (the only deployment shape this sandbox runs). If a future
deployment scales to multiple API server processes/instances behind a load balancer, a client
connected to instance A would never receive a broadcast whose triggering event happened to be
consumed by instance B's own `BrokerFanOutWorker` — cross-instance fan-out would need a
different `ConnectionManager`-satisfying adapter (e.g. Redis Pub/Sub to rebroadcast across
instances). Not needed for this phase's actual deployment shape; the seam is clean (same
`ConnectionManager` interface) for whenever it is.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Protocol

from fastapi import WebSocketDisconnect
from redis.asyncio import Redis

from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerConsumer
from raad.core.events.redis_streams import RedisDeadLetterQueue, RedisStreamsBrokerConsumer
from raad.core.logging.setup import get_logger
from raad.core.security.tokens import TokenService, resolve_principal_from_access_token
from raad.core.tenancy.principal import Principal
from raad.core.time.clock import Clock
from raad.core.workers.base import Worker
from raad.core.workers.retry import ExponentialBackoffRetryPolicy, RetryPolicy

logger = get_logger("raad.realtime")


class WsCloseCode:
    """Application close codes in the 4000-4999 private-use range (RFC 6455 §7.4.2 — no
    IANA-assigned meaning, safe for this codebase's own convention). Chosen to mirror the
    HTTP status codes the same situations map to elsewhere in this API (`core/errors/
    handlers.py`), for operator familiarity — not a WebSocket-spec-defined mapping."""

    BAD_REQUEST = 4400
    UNAUTHENTICATED = 4401
    FORBIDDEN = 4403


class RealtimeConnection(Protocol):
    """The shape both `ConnectionManager` and `authenticate_connection` need from "a
    connection" — satisfied by `starlette.websockets.WebSocket` (and by `fastapi.WebSocket`,
    a subclass) without importing either here, and trivially fakeable in tests."""

    async def send_json(self, data: Any) -> None: ...

    async def receive_json(self) -> Any: ...

    async def close(self, code: int = 1000) -> None: ...


class ConnectionManager:
    """Keyed registry of live connections (key: `vehicle_id` for tracking, `recipient_user_id`
    for notifications) — one instance per channel, not shared between the two, since their key
    spaces are unrelated. `asyncio.Lock`-guarded: register/unregister/iteration all happen from
    whichever task is running that connection's own receive loop, plus the realtime fan-out
    worker's own tick, all interleaved on one event loop — the lock keeps the registry's
    internal dict mutations atomic against that interleaving (safety, not raw concurrency, since
    a single-threaded event loop already serializes actual execution).

    Each connection is registered **with the `Principal` that authenticated it** — not just the
    bare connection — because the tracking fan-out handler re-evaluates `TrackingVisibilityPolicy`
    per subscriber on every position push (`modules/tracking/api/ws.py`'s own docstring explains
    why), and needs to know *whose* access to re-check. `Principal` is a plain, hashable-by-value
    `@dataclass(frozen=True)`, cheap to carry alongside the connection."""

    def __init__(self) -> None:
        self._by_key: dict[str, dict[RealtimeConnection, Principal]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self, key: str, connection: RealtimeConnection, principal: Principal
    ) -> None:
        async with self._lock:
            self._by_key.setdefault(key, {})[connection] = principal

    async def unregister(self, key: str, connection: RealtimeConnection) -> None:
        async with self._lock:
            entries = self._by_key.get(key)
            if entries is None:
                return
            entries.pop(connection, None)
            if not entries:
                del self._by_key[key]

    async def subscribers_for(self, key: str) -> list[tuple[RealtimeConnection, Principal]]:
        async with self._lock:
            return list(self._by_key.get(key, {}).items())

    async def connection_count(self) -> int:
        """Total registered connections across every key — used only for tests/observability,
        never for routing a broadcast."""
        async with self._lock:
            return sum(len(v) for v in self._by_key.values())


async def authenticate_connection(
    connection: RealtimeConnection, *, token_service: TokenService, timeout_seconds: float
) -> Principal | None:
    """The **single** WebSocket auth entry point for both `/ws/tracking` and
    `/ws/notifications` (`modules/tracking/api/ws.py`/`modules/notifications/api/ws.py` both
    call this, never their own copy — the first draft of this feature mistakenly duplicated it
    per module before being caught in review). Waits for the documented first `auth` frame
    (API Contracts §11.1: "access token passed at connection... first `auth` frame") —
    `{"type":"auth","token":"<access_jwt>"}` — within `timeout_seconds`, then verifies it via
    `core.security.tokens.resolve_principal_from_access_token`, the exact function
    `SecurityContextMiddleware` uses for HTTP requests (that middleware cannot run for a
    WebSocket connection at all — Starlette's `BaseHTTPMiddleware` only wraps ASGI `http`
    scope; see that function's own docstring). Returns `None` on timeout, malformed frame, or
    an invalid/expired/wrong-type token — every caller closes with `WsCloseCode.UNAUTHENTICATED`
    in all such cases, so this function never needs to distinguish *why* auth failed. A
    `WebSocketDisconnect` (the client left before sending anything) is deliberately not
    swallowed here — it propagates so the caller's own connection-lifecycle handling deals with
    it as an ordinary early disconnect, not an "authentication failed, now close" case."""
    try:
        message = await asyncio.wait_for(connection.receive_json(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return None
    except WebSocketDisconnect:
        raise
    except Exception:
        return None

    if not isinstance(message, dict) or message.get("type") != "auth":
        return None
    token = message.get("token")
    if not isinstance(token, str) or not token:
        return None
    return resolve_principal_from_access_token(token_service, token)


class BrokerFanOutWorker(Worker):
    """Ticks one `BrokerConsumer` and dispatches each event to one handler — the exact
    `core.workers.base.Worker` lifecycle `interfaces/workers/notification_worker.
    NotificationWorker` already establishes for the (separate-process) Notification Worker,
    reused here verbatim since the shape ("tick a consumer, dispatch to a handler, never let one
    bad tick kill the loop") is identical; only the handler and the hosting process differ."""

    def __init__(
        self,
        name: str,
        *,
        clock: Clock,
        consumer: BrokerConsumer,
        handler: Callable[[DomainEvent], Awaitable[None]],
    ) -> None:
        super().__init__(name, clock)
        self._consumer = consumer
        self._handler = handler

    async def run_once(self) -> None:
        await self._consumer.consume(self._handler)


def build_realtime_broker_consumer(
    *, broker_url: str, group_name: str, clock: Clock, retry_policy: RetryPolicy | None = None
) -> BrokerConsumer:
    """Constructs a fresh `RedisStreamsBrokerConsumer` for one realtime channel's own consumer
    group, independent of `core/di/bootstrap.py`'s `BrokerConsumer` singleton (reserved for the
    Notification Worker's own `notification-worker` group — see module docstring). A fresh
    `Redis.from_url` client per call mirrors `build_container`'s own "separate client per
    logical consumer" precedent."""
    redis_client = Redis.from_url(broker_url, decode_responses=True)
    dead_letter_queue = RedisDeadLetterQueue(redis_client)
    policy = retry_policy or ExponentialBackoffRetryPolicy(
        max_attempts=5, base_delay_seconds=1.0, max_delay_seconds=300.0
    )
    return RedisStreamsBrokerConsumer(
        redis_client,
        group_name=group_name,
        retry_policy=policy,
        dead_letter_queue=dead_letter_queue,
    )


async def safe_close(connection: RealtimeConnection, code: int) -> None:
    """Closes a connection, swallowing any error — this only ever runs from inside a
    `BrokerFanOutWorker` tick's own event-handling loop (cleaning up one now-unauthorized or
    now-ended subscriber among potentially several), and a single connection already being
    half-closed/errored must never abort that loop for every *other* subscriber still being
    processed (`core.workers.base.Worker._tick`'s own "one bad tick never kills the loop"
    principle, applied one level down)."""
    try:
        await connection.close(code=code)
    except Exception:  # noqa: BLE001 - cleanup best-effort, never propagate
        logger.debug("realtime_connection_close_failed", exc_info=True)
