"""Connection Manager (Phase 9.1 — Transport Layer only; Phase 2 §5.1, Phase 3.4 §2/§20).

Owns the set of currently-accepted connections: accepts new ones, registers a
`ConnectionSession` per connection (`session/registry.py`), routes each connection's raw
frames to an injected `on_frame` callback (protocol-agnostic — see `connection.py`'s module
docstring), and runs the periodic idle-timeout sweep that is this phase's "heartbeat timeout
infrastructure (framework only, not protocol handling)": it only knows "no bytes arrived
recently for this session," never anything about JT808's `0x0002` heartbeat message.

**Phase 9.2 additions (minimal, additive — transport behavior is unchanged):** an optional
`on_connection_closed` hook, fired after this manager's own transport-registry cleanup, lets
the session layer (`DeviceSessionManager.handle_connection_closed`) close whatever
`DeviceSession` was bound to a connection that just dropped, without `ConnectionManager`
importing anything from `session/device_session*.py` — the dependency points one way, from
session layer to transport layer, never back (".claude/rules": keep the layers separate).
`close_connection()` is the matching public entry point the session layer uses to request a
*specific* connection be closed (superseding a duplicate terminal, ADR-808-8) without needing
direct access to a `Connection` object.

**Phase 9.4 addition:** `send_to_connection()` — the same "public entry point, no direct
`Connection` access" pattern, used by the Message Dispatcher (`dispatcher/dispatcher.py`) to
send automatic-acknowledgment frames back to whichever connection a message arrived on.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Awaitable, Callable

from src.connection.connection import Connection
from src.logging_setup import get_logger, log_with_fields
from src.session.registry import SessionRegistry
from src.session.session import ConnectionSession

logger = get_logger("jt808.connection_manager")

FrameHandler = Callable[[str, bytes], Awaitable[None]]


async def _default_on_frame(connection_id: str, frame: bytes) -> None:
    """No dispatcher exists yet (Phase 9.1 scope) — frames are received and logged
    (`Connection._read_loop`'s own `frame_received` log) but never parsed or routed. A later
    phase injects a real `on_frame` (the Packet Dispatcher) here without changing
    `ConnectionManager`."""


class ConnectionManager:
    def __init__(
        self,
        *,
        session_registry: SessionRegistry,
        read_chunk_size: int,
        max_frame_size: int,
        idle_timeout_seconds: float,
        sweep_interval_seconds: float,
        on_frame: FrameHandler | None = None,
        on_connection_closed: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._sessions = session_registry
        self._read_chunk_size = read_chunk_size
        self._max_frame_size = max_frame_size
        self._idle_timeout_seconds = idle_timeout_seconds
        self._sweep_interval_seconds = sweep_interval_seconds
        self._on_frame = on_frame or _default_on_frame
        self._on_connection_closed = on_connection_closed
        self._connections: dict[str, Connection] = {}
        self._sweep_task: asyncio.Task | None = None

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """The callback `asyncio.start_server` invokes per accepted TCP connection."""
        connection_id = str(uuid.uuid4())
        remote_address = str(writer.get_extra_info("peername"))
        session = ConnectionSession(
            connection_id=connection_id, remote_address=remote_address
        )
        connection = Connection(
            connection_id=connection_id,
            reader=reader,
            writer=writer,
            read_chunk_size=self._read_chunk_size,
            max_frame_size=self._max_frame_size,
            on_frame=self._on_frame,
            on_activity=session.touch,
            on_close=self._handle_connection_closed,
        )
        self._connections[connection_id] = connection
        self._sessions.add(session)
        connection.start()

    async def _handle_connection_closed(self, connection_id: str) -> None:
        self._connections.pop(connection_id, None)
        session = self._sessions.get(connection_id)
        if session is not None:
            session.mark_closed()
        self._sessions.remove(connection_id)
        if self._on_connection_closed is not None:
            await self._on_connection_closed(connection_id)

    async def close_connection(self, connection_id: str, *, reason: str) -> None:
        """Public entry point for other layers to request a specific connection be closed
        (e.g. the session layer superseding a duplicate terminal) without needing direct
        access to the `Connection` object. A no-op if the connection is already gone."""
        connection = self._connections.get(connection_id)
        if connection is not None:
            await connection.close(reason=reason)

    async def send_to_connection(self, connection_id: str, data: bytes) -> None:
        """Public entry point for other layers to send bytes on a specific connection (Phase
        9.4 addition — the Message Dispatcher's automatic-response mechanism, `dispatcher/
        dispatcher.py`) without needing direct access to the `Connection` object. A no-op if
        the connection is already gone (the terminal disconnected before the response could
        be sent — not an error, nothing to notify)."""
        connection = self._connections.get(connection_id)
        if connection is not None:
            await connection.send(data)

    def start_sweep(self) -> None:
        self._sweep_task = asyncio.create_task(self._sweep_loop())

    async def stop_sweep(self) -> None:
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None

    async def _sweep_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._sweep_interval_seconds)
                await self._sweep_once()
        except asyncio.CancelledError:
            raise

    async def _sweep_once(self) -> None:
        now = time.monotonic()
        stale_ids = [
            session.connection_id
            for session in self._sessions.all()
            if now - session.last_activity_at > self._idle_timeout_seconds
        ]
        for connection_id in stale_ids:
            connection = self._connections.get(connection_id)
            if connection is not None:
                log_with_fields(
                    logger, 30, "connection_idle_timeout", connection_id=connection_id
                )
                await connection.close(reason="idle_timeout")

    async def shutdown(self) -> None:
        """Graceful shutdown: stop the sweep task, close every connection, wait for cleanup.
        Idempotent per-connection via `Connection.close`'s own guard."""
        await self.stop_sweep()
        for connection_id in list(self._connections.keys()):
            connection = self._connections.get(connection_id)
            if connection is not None:
                await connection.close(reason="server_shutdown")

    @property
    def connection_count(self) -> int:
        return len(self._connections)
