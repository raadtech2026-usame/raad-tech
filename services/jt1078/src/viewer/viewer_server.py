"""`ViewerServer` — the token-gated WS-FLV delivery endpoint (ADR-0024 §5 point 2, §6 point 6,
§15). **Performs no user authentication and no RBAC of its own** — the *only* check is the signed,
single-use viewer token in the connection's own query string (`?token=...`), verified against
`session/viewer_token.py`. A missing/invalid/expired/already-used token, or a token whose
session doesn't exist or isn't currently broadcast-ready, is rejected with a WebSocket close frame
before any FLV byte is ever sent — D5 holds structurally here: there is no code path in this
class that can reach `hub.add_viewer` without a verified token first.

**ADR-0036: a second, `"uplink"`-role token branch.** `verify_token_signature` now returns
`(session_id, role)`. `role="viewer"` (default) is the complete, unchanged pre-existing behavior
below. `role="uplink"` is a distinct connection kind for an intercom session's operator-mic audio:
it is never registered with a `SessionBroadcastHub` (it is not a broadcast target — sending it
FLV bytes would be meaningless, since it carries no video/audio pipeline of its own) and never
counted in `session_manager.add_viewer`/`remove_viewer` (that counter drives idle-timeout
teardown for *viewing*, a materially different concept from an active talk session, which the
uplink connection's own lifetime already tracks by simply being open). Instead, every inbound
*binary* WS frame on an uplink connection is forwarded verbatim to
`session/uplink_registry.IngestConnectionRegistry.send_audio` — the bridge to the device's own
live ingest socket.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Coroutine

from src.logging_setup import get_logger, log_with_fields
from src.session.session_manager import SessionManager
from src.session.uplink_registry import IngestConnectionRegistry
from src.session.viewer_token import SingleUseTokenGuard, verify_token_signature
from src.viewer.broadcast_hub import SessionBroadcastHub
from src.viewer.websocket_server import (
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_PING,
    WebSocketConnection,
    WebSocketHandshakeError,
)

logger = get_logger("jt1078_relay.viewer.server")

_ROLE_UPLINK = "uplink"

#: RFC 6455 §5.5.2 server-initiated keepalive (2026-09-02) — this hand-rolled WebSocket server
#: previously never sent a ping of its own (only ever *replied* to one, `WebSocketConnection.
#: send_pong`). Added while diagnosing a real, physically-observed pattern: every browser<->relay
#: WebSocket (both this server's ordinary viewer connections and ADR-0036's intercom uplink)
#: measured almost exactly ~32s of lifetime before an abrupt `IncompleteReadError`, uniformly,
#: regardless of when the connection was opened or how much media was actively flowing through
#: it — evidence against an application-level idle timeout (media was flowing continuously) and
#: for something in the network path between the browser and this relay's exposed port treating
#: the connection as stale absent WebSocket-level control-frame activity. This constant is
#: intentionally well under that ~32s figure so a real keepalive cycle completes several times
#: before whatever is timing the connection out would ever fire.
_PING_INTERVAL_SECONDS = 10.0


class ViewerServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        secret: bytes,
        token_guard: SingleUseTokenGuard,
        session_manager: SessionManager,
        hubs: dict[str, SessionBroadcastHub],
        uplink_registry: IngestConnectionRegistry | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._secret = secret
        self._token_guard = token_guard
        self._session_manager = session_manager
        self._hubs = hubs
        #: ADR-0036. `None` (default) means no intercom uplink token can ever verify successfully
        #: (`_authorize` below) — every pre-existing test/caller that doesn't pass one keeps this
        #: server's exact prior "viewer-only" behavior.
        self._uplink_registry = uplink_registry
        self._server: asyncio.base_events.Server | None = None
        self._connections: set[asyncio.StreamWriter] = set()
        #: Bug 1 fix: the browser's own uplink WebSocket connection, per session — a session can
        #: have at most one (a viewer token's `role="uplink"` is single-use, `viewer_token.py`),
        #: so unlike `_hubs`/`SessionBroadcastHub` (which can fan out to many viewers) this is a
        #: direct `session_id -> connection` map. Lets `close_session` below actively close it
        #: when the session becomes terminal, mirroring what `SessionBroadcastHub.close_all` now
        #: does for the downlink side.
        self._uplink_connections: dict[str, WebSocketConnection] = {}

    @property
    def bound_port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("ViewerServer is not started.")
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_connection, self._host, self._port)

    async def stop(self) -> None:
        for writer in list(self._connections):
            writer.close()
        self._connections.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._connections.add(writer)
        connection = WebSocketConnection(reader, writer)
        session_id: str | None = None
        role: str = "viewer"
        is_broadcast_viewer = False
        try:
            try:
                _path, query = await connection.accept()
            except WebSocketHandshakeError:
                await connection.reject()
                return

            token = (query.get("token") or [None])[0]
            authorized = await self._authorize(token)
            if authorized is None:
                await connection.send_close(code=4001, reason=b"invalid_token")
                return
            session_id, role = authorized

            if role == _ROLE_UPLINK:
                # ADR-0036: no broadcast hub involvement at all — this connection exists only to
                # forward the operator's own mic audio toward the device, never to receive FLV
                # bytes. A missing/unbound registry means intercom simply isn't configured on this
                # deployment; reject cleanly rather than accept a connection that can never do
                # anything.
                if self._uplink_registry is None:
                    await connection.send_close(code=4004, reason=b"uplink_not_available")
                    return
                log_with_fields(logger, 20, "uplink_connected", session_id=session_id)
                # Bug 1 fix: tracked so `close_session` can proactively close this connection the
                # instant the session becomes terminal, instead of leaving it open and silent.
                self._uplink_connections[session_id] = connection
                try:
                    await self._pump_with_keepalive(
                        connection, self._pump_uplink_frames(connection, session_id)
                    )
                except Exception as exc:  # noqa: BLE001 - live-verified 2026-09-01: an ordinary
                    # client-initiated disconnect (operator navigating away/closing the tab mid-
                    # call) can unwind this loop's own blocked `read_frame()` via more exception
                    # shapes than the narrower `(ConnectionError, OSError,
                    # asyncio.IncompleteReadError)` this originally caught — confirmed live
                    # against the physical bench unit: that narrower catch still let one through,
                    # surfacing as asyncio's own "Unhandled exception in client_connected_cb" (a
                    # per-connection task, not a `run_forever` loop, so nothing else was affected,
                    # but exactly the "must catch and log, never let one escape unhandled"
                    # discipline `.claude/rules`/this codebase's own `run_forever` consumers
                    # already hold themselves to). A server-initiated close (`close_session`,
                    # running on a different task) racing this loop's own read is the same
                    # ordinary-disconnect shape, not a real error either.
                    log_with_fields(
                        logger, 20, "uplink_connection_closed", session_id=session_id,
                        reason=type(exc).__name__,
                    )
                return

            hub = self._hubs.get(session_id)
            if hub is None:
                await connection.send_close(code=4004, reason=b"session_not_active")
                return

            try:
                await hub.add_viewer(connection)
                is_broadcast_viewer = True
                self._session_manager.add_viewer(session_id)
                log_with_fields(logger, 20, "viewer_connected", session_id=session_id)

                await self._pump_with_keepalive(connection, self._pump_control_frames(connection))
            except Exception as exc:  # noqa: BLE001 - same reasoning as the uplink branch above:
                # an ordinary disconnect (client-initiated, or a proactive `close_session` racing
                # this loop's own blocked read) can surface as more exception shapes than a
                # narrow network-error tuple catches, live-confirmed for the uplink branch above.
                log_with_fields(
                    logger, 20, "viewer_connection_closed", session_id=session_id,
                    reason=type(exc).__name__,
                )
        finally:
            self._connections.discard(writer)
            if session_id is not None and role == _ROLE_UPLINK:
                self._uplink_connections.pop(session_id, None)
                log_with_fields(logger, 20, "uplink_disconnected", session_id=session_id)
            elif session_id is not None and is_broadcast_viewer:
                hub = self._hubs.get(session_id)
                if hub is not None:
                    hub.remove_viewer(connection)
                self._session_manager.remove_viewer(session_id)
                log_with_fields(logger, 20, "viewer_disconnected", session_id=session_id)
            await connection.close_transport()

    async def close_session(
        self,
        session_id: str,
        *,
        hub: SessionBroadcastHub | None,
        code: int,
        reason: bytes,
    ) -> None:
        """Bug 1 fix — the relay's own composition root (`relay.py._on_session_removed`) calls
        this the instant a session becomes terminal (`FAILED` via ingest timeout, or `ENDED` via
        an explicit stop/idle-timeout/parent-access-revoked teardown). Without this, a browser
        already connected before the session ended is left holding an open, silent WebSocket
        forever — no data, no close frame — which is exactly why `useIntercomController`'s phase
        machine could get stuck showing "Connecting intercom..." indefinitely.

        `hub` is passed in directly rather than looked up from `self._hubs` here: the caller has
        already popped it out of that (shared) dict by the time this runs, so a fresh lookup
        would always miss. Closing the hub's own viewers is delegated to `SessionBroadcastHub.
        close_all` (per-viewer failure isolation, unchanged); the browser's own uplink connection
        (if any — only ever present for an `INTERCOM` session with `startTalking` wired up) is
        looked up and closed the same way. Both are best-effort — a connection that already
        disconnected on its own is a normal, expected no-op, never an error here."""
        if hub is not None:
            await hub.close_all(code=code, reason=reason)
        uplink_connection = self._uplink_connections.pop(session_id, None)
        if uplink_connection is not None:
            try:
                await uplink_connection.send_close(code=code, reason=reason)
            except Exception:  # noqa: BLE001 - best-effort; the peer may already be gone
                pass

    async def _authorize(self, token: str | None) -> tuple[str, str] | None:
        """Signature/expiry check *and* single-use claim — both must pass. Claiming *after* the
        signature check (not before) means a malformed/forged token never consumes a real slot in
        the single-use guard's own state. Returns `(session_id, role)` (ADR-0036)."""
        if not token:
            return None
        verified = verify_token_signature(token, secret=self._secret)
        if verified is None:
            return None
        session_id, role = verified
        if not await self._token_guard.claim(token):
            return None
        return session_id, role

    async def _pump_with_keepalive(
        self, connection: WebSocketConnection, pump: Coroutine[Any, Any, None]
    ) -> None:
        """Runs `pump` (one connection's own read loop, `_pump_control_frames`/
        `_pump_uplink_frames`) exactly as before — directly awaited, so its own return value/
        exception propagate to the caller completely unchanged — while a periodic keepalive ping
        (module constant `_PING_INTERVAL_SECONDS` docstring) runs *concurrently*, on its own
        independent task. Deliberately never wraps/cancels `pump` itself (e.g. via
        `asyncio.wait_for`): cancelling a `StreamReader.readexactly()` mid-call can silently
        discard bytes it had already pulled off the socket into its own local buffer before
        cancellation, desynchronizing this connection's own frame boundary — a correctness risk
        for the read side this design avoids entirely by keeping the ping loop on a fully
        separate task that only ever writes, never reads."""
        ping_task = asyncio.ensure_future(self._ping_loop(connection))
        try:
            await pump
        finally:
            ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ping_task

    async def _ping_loop(self, connection: WebSocketConnection) -> None:
        """Sends one WS-level ping every `_PING_INTERVAL_SECONDS` for as long as this task lives.
        A real browser WebSocket client responds to a server ping transparently, at the protocol
        level — no application/JS change needed on the frontend to produce the resulting pong,
        and this relay's own read loops already tolerate an unrecognized opcode without erroring
        (the pong itself needs no explicit handling here). A send failure means the connection is
        already gone; this loop simply returns rather than raising — the read loop running
        concurrently (`pump` in `_pump_with_keepalive`) is the authoritative signal for that, via
        its own EOF/reset detection, unchanged by this addition."""
        try:
            while True:
                await asyncio.sleep(_PING_INTERVAL_SECONDS)
                await connection.send_ping()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the connection is already gone; nothing more to do
            return

    async def _pump_control_frames(self, connection: WebSocketConnection) -> None:
        """Reads whatever the viewer's own client sends (close/ping) so a disconnect or explicit
        close is detected promptly rather than only via a TCP-level error on the next send — this
        relay never expects a data frame *from* an ordinary (downlink) viewer."""
        while True:
            result = await connection.read_frame()
            if result is None:
                break
            opcode, _payload = result
            if opcode == OPCODE_CLOSE:
                break
            if opcode == OPCODE_PING:
                await connection.send_pong()

    async def _pump_uplink_frames(self, connection: WebSocketConnection, session_id: str) -> None:
        """ADR-0036: the intercom uplink's own read loop — every *binary* frame the browser sends
        is the operator's own raw G.711A-encoded mic audio (already encoded client-side,
        ADR-0036 §5), forwarded verbatim to the device's ingest connection via
        `IngestConnectionRegistry.send_audio`. Close/ping handled identically to the ordinary
        viewer path; any other opcode is ignored (never crashes the loop)."""
        assert self._uplink_registry is not None  # guarded by the caller
        while True:
            result = await connection.read_frame()
            if result is None:
                break
            opcode, payload = result
            if opcode == OPCODE_CLOSE:
                break
            if opcode == OPCODE_PING:
                await connection.send_pong()
                continue
            if opcode == OPCODE_BINARY and payload:
                await self._uplink_registry.send_audio(session_id, payload)
