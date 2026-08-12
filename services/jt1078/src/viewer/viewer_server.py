"""`ViewerServer` — the token-gated WS-FLV delivery endpoint (ADR-0024 §5 point 2, §6 point 6,
§15). **Performs no user authentication and no RBAC of its own** — the *only* check is the signed,
single-use viewer token in the connection's own query string (`?token=...`), verified against
`session/viewer_token.py`. A missing/invalid/expired/already-used token, or a token whose
session doesn't exist or isn't currently broadcast-ready, is rejected with a WebSocket close frame
before any FLV byte is ever sent — D5 holds structurally here: there is no code path in this
class that can reach `hub.add_viewer` without a verified token first.
"""

from __future__ import annotations

import asyncio

from src.logging_setup import get_logger, log_with_fields
from src.session.session_manager import SessionManager
from src.session.viewer_token import SingleUseTokenGuard, verify_token_signature
from src.viewer.broadcast_hub import SessionBroadcastHub
from src.viewer.websocket_server import (
    OPCODE_CLOSE,
    OPCODE_PING,
    WebSocketConnection,
    WebSocketHandshakeError,
)

logger = get_logger("jt1078_relay.viewer.server")


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
    ) -> None:
        self._host = host
        self._port = port
        self._secret = secret
        self._token_guard = token_guard
        self._session_manager = session_manager
        self._hubs = hubs
        self._server: asyncio.base_events.Server | None = None
        self._connections: set[asyncio.StreamWriter] = set()

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
        try:
            try:
                _path, query = await connection.accept()
            except WebSocketHandshakeError:
                await connection.reject()
                return

            token = (query.get("token") or [None])[0]
            session_id = await self._authorize(token)
            if session_id is None:
                await connection.send_close(code=4001, reason=b"invalid_token")
                return

            hub = self._hubs.get(session_id)
            if hub is None:
                await connection.send_close(code=4004, reason=b"session_not_active")
                return

            await hub.add_viewer(connection)
            self._session_manager.add_viewer(session_id)
            log_with_fields(logger, 20, "viewer_connected", session_id=session_id)

            await self._pump_control_frames(connection)
        finally:
            self._connections.discard(writer)
            if session_id is not None:
                hub = self._hubs.get(session_id)
                if hub is not None:
                    hub.remove_viewer(connection)
                self._session_manager.remove_viewer(session_id)
                log_with_fields(logger, 20, "viewer_disconnected", session_id=session_id)
            await connection.close_transport()

    async def _authorize(self, token: str | None) -> str | None:
        """Signature/expiry check *and* single-use claim — both must pass. Claiming *after* the
        signature check (not before) means a malformed/forged token never consumes a real slot in
        the single-use guard's own state."""
        if not token:
            return None
        session_id = verify_token_signature(token, secret=self._secret)
        if session_id is None:
            return None
        if not await self._token_guard.claim(token):
            return None
        return session_id

    async def _pump_control_frames(self, connection: WebSocketConnection) -> None:
        """Reads whatever the viewer's own client sends (close/ping) so a disconnect or explicit
        close is detected promptly rather than only via a TCP-level error on the next send — this
        relay never expects a data frame *from* a viewer."""
        while True:
            result = await connection.read_frame()
            if result is None:
                break
            opcode, _payload = result
            if opcode == OPCODE_CLOSE:
                break
            if opcode == OPCODE_PING:
                await connection.send_pong()
