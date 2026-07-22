"""Realtime WebSocket surface for `tracking` (`/ws/tracking`, API Contracts §11.1/§11.2;
Backend LLD §16.1/§16.2). Mounted by `interfaces/http/ws.py`, the same "one router per module,
aggregated centrally" shape §16.1 already establishes for REST (`tracking_router` in
`interfaces/http/api_v1.py`).

**Auth model — "first auth frame," not a subprotocol** (API Contracts §11.1 documents both as
acceptable). After `websocket.accept()`, the client's first message must be
`{"type":"auth","token":"<access_jwt>"}` within `settings.websocket.auth_frame_timeout_seconds`;
anything else (timeout, malformed frame, invalid/expired token) closes with
`WsCloseCode.UNAUTHENTICATED`. The auth handshake itself — waiting for that frame and verifying
the token — is `interfaces/http/realtime.authenticate_connection`, the **one** shared
implementation both this module and `notifications.api.ws` call (never a per-module copy); it
in turn calls `core.security.tokens.resolve_principal_from_access_token`, the exact function
`SecurityContextMiddleware` uses for HTTP requests (that middleware cannot run for a WebSocket
connection at all; see its own docstring for why).

**Subscribe authorization reuses `interfaces/http/policy_guards.resolve_tracking_decision`
verbatim** — the same `TrackingVisibilityPolicy` composition `GET /tracking/vehicles/{id}/
latest`/`GET /tracking/trips/{id}/positions` already enforce, via the new
`resolve_vehicle_tracking_context` helper that file now also exposes (built for this module,
since the REST routes' own `organization_id` resolution assumes a position already exists —
this module must also support subscribing to a vehicle that hasn't reported a position yet).
A denied/unknown-vehicle subscribe closes with `WsCloseCode.FORBIDDEN` — deliberately not
distinguishing "vehicle doesn't exist" from "exists but not authorized," mirroring this
codebase's own 404-over-403 cross-tenant-probing-avoidance posture, arguably even more
important over a close-code channel than an HTTP body.

**One active vehicle subscription per connection.** API Contracts §11.2 documents a single
subscribe example; a second `subscribe` message on the same connection replaces the first
(unsubscribing from the prior `vehicle_id`) rather than accumulating multiple simultaneous
subscriptions — a deliberate, flagged simplification, not a documented multi-subscribe
protocol.

**Live position push re-checks authorization on every send, not just at subscribe time** —
this is how "the socket is closed server-side immediately on a CR-1 revoking event" (§11.2) is
actually achieved for `SubscriptionExpired`/`StudentAssignmentRemoved`/`StudentTransferred`/
`StudentGraduated`/`StudentDisabled` (the actual, shipped CR-1-revocation events —
`transport_ops.domain.events`), rather than a translation layer resolving each event's
`student_id`/`assignment_id` back to the specific `vehicle_id`(s) it affects. That resolution
gap is real and already flagged elsewhere in this codebase (`notifications/domain/events.py`'s
own module docstring: API Contracts §13.2's single `student.assignment_changed` wire event
doesn't match the four separate, no-`student_id`-payload events `transport_ops` actually
emits) — building a new one here, just for this feature, would be inventing a resolution this
phase's own instruction doesn't authorize. Re-running `resolve_tracking_decision` on every
position forward achieves the identical safety property (a denied parent never receives
another frame) without it: the very next position event for that vehicle re-evaluates the
policy fresh against current DB state and drops/closes the now-unauthorized subscriber. Only
`TripEnded` gets an immediate, explicit `subscription_closed` frame + close — a clean,
certain, single-event, 1:1-`vehicle_id` case with no such resolution gap.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.logging.setup import get_logger
from raad.core.security.tokens import TokenService
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.policy_guards import (
    resolve_tracking_decision,
    resolve_vehicle_tracking_context,
)
from raad.interfaces.http.realtime import (
    ConnectionManager,
    WsCloseCode,
    authenticate_connection,
    safe_close,
)

tracking_ws_router = APIRouter()
logger = get_logger("raad.tracking.ws")

# The two broker `event_type`s this channel reacts to. `DevicePositionReported` is this
# codebase's own PascalCase naming (`.claude/rules/naming.md`) for API Contracts §13.2's
# `device.position_reported` row — no producer exists anywhere in this repo yet (the JT808
# service is a separate, not-yet-built deployable, `.claude/rules/architecture.md` #2), so
# there is no prior literal string to stay consistent with the way `TripStarted`/`TripEnded`
# already exist; PascalCase is chosen for consistency with every domain event this codebase
# *does* already emit, flagged here rather than silently assumed. Payload field names
# (`vehicle_id`, `trip_id`, `lat`, `lng`, `speed_kph`, `heading_deg`, `event_time`) are read
# directly from API Contracts §11.2's own fully-specified wire frame — the more authoritative,
# exact contract, vs. §13.2's abridged "key payload: vehicle_id, lat, lng, speed, heading,
# event_time, is_backfill" prose row.
POSITION_EVENT_TYPE = "DevicePositionReported"
TRIP_ENDED_EVENT_TYPE = "TripEnded"


async def handle_subscribe(
    message: dict[str, Any],
    *,
    websocket: WebSocket,
    principal: Principal,
    container: Container,
    connections: ConnectionManager,
    current_vehicle_id: str | None,
) -> str | None:
    """Handles one `{"type":"subscribe","channel":"vehicle","vehicle_id":...}` frame. Returns
    the newly-subscribed `vehicle_id` on success (the caller tracks this as its own connection
    state, `current_vehicle_id` for the *next* call, achieving the "one subscription per
    connection, a new subscribe replaces the old" rule from this module's own docstring) or
    `None` if the connection was closed (denied/invalid) — the caller must stop reading after
    a `None` return.

    **Every exception raised while resolving the subscribe is caught here, not left to
    propagate** — an ASGI-level smoke test caught this as a real bug during review: a
    malformed `vehicle_id` (not a 26-character ULID) fails `VehicleId.__post_init__`'s own
    validation with a `DomainError`, and FastAPI's global exception handler
    (`core/errors/handlers.py`) only knows how to turn an `AppError` into an HTTP `JSONResponse`
    — which is not a valid ASGI message on an *already-accepted* WebSocket, corrupting the
    connection instead of closing it cleanly. `core/errors/exceptions.py`'s own module
    docstring anticipates exactly this: "other delivery mechanisms (workers, WebSocket) can map
    the same exceptions to their own transport without duplicating the hierarchy" — this
    `except Exception` is that mapping for this transport. Deliberately broader than just
    `AppError`: a not-yet-configured infra port (e.g. `ScopeResolver` unbound because `db.url`
    isn't set) raises a bare `LookupError`, outside the `AppError` hierarchy entirely — that is
    a real misconfiguration worth logging loudly (`logger.exception`, so it stays visible to
    operators), but it must *still* result in a clean socket close, never a corrupted ASGI
    transport, mirroring `core.workers.base.Worker._tick`'s own "one bad operation is logged,
    never left to crash the surrounding loop" principle applied to a WebSocket connection
    instead of a worker tick."""
    vehicle_id = message.get("vehicle_id")
    if message.get("channel") != "vehicle" or not isinstance(vehicle_id, str) or not vehicle_id:
        await websocket.close(code=WsCloseCode.BAD_REQUEST)
        return None

    if current_vehicle_id is not None:
        await connections.unregister(current_vehicle_id, websocket)

    try:
        context = await resolve_vehicle_tracking_context(
            vehicle_id=vehicle_id, container=container
        )
        if context is None:
            await websocket.close(code=WsCloseCode.FORBIDDEN)
            return None
        organization_id, is_trip_active = context

        decision = await resolve_tracking_decision(
            principal=principal,
            organization_id=organization_id,
            vehicle_id=vehicle_id,
            is_trip_active=is_trip_active,
            container=container,
        )
    except Exception:  # noqa: BLE001 - see this function's own docstring
        logger.exception(
            "tracking_subscribe_failed", extra={"vehicle_id": vehicle_id}
        )
        await websocket.close(code=WsCloseCode.BAD_REQUEST)
        return None

    if not decision.allowed:
        await websocket.close(code=WsCloseCode.FORBIDDEN)
        return None

    await connections.register(vehicle_id, websocket, principal)
    return vehicle_id


def _position_frame(payload: dict[str, Any]) -> dict[str, Any]:
    """API Contracts §11.2's documented server->client position frame, built directly from the
    broker event's payload — see this module's own docstring for the field-naming reasoning."""
    return {
        "type": "position",
        "vehicle_id": payload.get("vehicle_id"),
        "trip_id": payload.get("trip_id"),
        "lat": payload.get("lat"),
        "lng": payload.get("lng"),
        "speed_kph": payload.get("speed_kph"),
        "heading_deg": payload.get("heading_deg"),
        "event_time": payload.get("event_time"),
    }


async def _handle_position_event(
    event: DomainEvent, *, connections: ConnectionManager, container: Container
) -> None:
    vehicle_id = event.payload.get("vehicle_id")
    if not vehicle_id:
        return
    subscribers = await connections.subscribers_for(vehicle_id)
    if not subscribers:
        return

    frame = _position_frame(event.payload)
    context = await resolve_vehicle_tracking_context(vehicle_id=vehicle_id, container=container)

    for connection, principal in subscribers:
        allowed = False
        if context is not None:
            organization_id, is_trip_active = context
            decision = await resolve_tracking_decision(
                principal=principal,
                organization_id=organization_id,
                vehicle_id=vehicle_id,
                is_trip_active=is_trip_active,
                container=container,
            )
            allowed = decision.allowed

        if not allowed:
            await connections.unregister(vehicle_id, connection)
            await safe_close(connection, WsCloseCode.FORBIDDEN)
            continue

        try:
            await connection.send_json(frame)
        except Exception:  # noqa: BLE001 - one broken subscriber must not block the rest
            await connections.unregister(vehicle_id, connection)
            await safe_close(connection, WsCloseCode.BAD_REQUEST)


async def _handle_trip_ended_event(
    event: DomainEvent, *, connections: ConnectionManager
) -> None:
    vehicle_id = event.payload.get("vehicle_id")
    if not vehicle_id:
        return
    subscribers = await connections.subscribers_for(vehicle_id)
    for connection, _principal in subscribers:
        await connections.unregister(vehicle_id, connection)
        try:
            await connection.send_json(
                {
                    "type": "subscription_closed",
                    "vehicle_id": vehicle_id,
                    "reason": "trip_ended",
                }
            )
        except Exception:  # noqa: BLE001 - best-effort notice before closing
            pass
        await safe_close(connection, 1000)


def build_tracking_fanout_handler(
    *, connections: ConnectionManager, container: Container
) -> Callable[[DomainEvent], Awaitable[None]]:
    """The handler `BrokerFanOutWorker` dispatches every consumed event to. Only reacts to the
    two event types this module's own docstring names; every other event on the shared
    `raad:events` stream is ignored (this consumer's own group still advances past it —
    `RedisStreamsBrokerConsumer.consume` acks every message its handler returns from without
    raising, regardless of whether the handler did anything with it)."""

    async def handler(event: DomainEvent) -> None:
        if event.event_type == POSITION_EVENT_TYPE:
            await _handle_position_event(event, connections=connections, container=container)
        elif event.event_type == TRIP_ENDED_EVENT_TYPE:
            await _handle_trip_ended_event(event, connections=connections)

    return handler


async def run_tracking_websocket(
    websocket: WebSocket,
    *,
    container: Container,
    connections: ConnectionManager,
    auth_frame_timeout_seconds: float,
) -> None:
    """The actual connection lifecycle: accept -> authenticate -> loop on subscribe frames ->
    clean up on disconnect. Thin by design (Backend LLD §16.2) — every authorization/business
    decision is delegated to `policy_guards`/`ConnectionManager`, never decided here."""
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

    current_vehicle_id: str | None = None
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            if message.get("type") == "subscribe":
                current_vehicle_id = await handle_subscribe(
                    message,
                    websocket=websocket,
                    principal=principal,
                    container=container,
                    connections=connections,
                    current_vehicle_id=current_vehicle_id,
                )
                if current_vehicle_id is None:
                    return
            # Unknown message types are ignored, forward-compatible with future frame kinds.
    except WebSocketDisconnect:
        pass
    finally:
        if current_vehicle_id is not None:
            await connections.unregister(current_vehicle_id, websocket)


@tracking_ws_router.websocket("")
async def tracking_websocket(websocket: WebSocket) -> None:
    container: Container = websocket.app.state.container
    connections: ConnectionManager = websocket.app.state.tracking_connections
    settings = websocket.app.state.settings
    await run_tracking_websocket(
        websocket,
        container=container,
        connections=connections,
        auth_frame_timeout_seconds=settings.websocket.auth_frame_timeout_seconds,
    )


__all__ = [
    "tracking_ws_router",
    "handle_subscribe",
    "build_tracking_fanout_handler",
    "run_tracking_websocket",
]
