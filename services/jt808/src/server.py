"""JT808 TCP transport service entrypoint (Phase 9.1 Transport Layer + Phase 9.2 Session
Management + Phase 9.3 Packet Parser; Phase 2 §5.1, Phase 3.4 §2/§5/§6). Wires config,
logging, the transport-level `SessionRegistry`/`ConnectionManager`, the device-level
`DeviceSessionRegistry`/`DeviceSessionManager`, and the `PacketParser` into a running
`asyncio.start_server`; handles SIGINT/SIGTERM for graceful shutdown (close every connection,
close every device session, stop both sweep tasks, stop the server) rather than letting the
process die with sockets mid-flight.

`DeviceSessionManager` is constructed *before* `ConnectionManager` so its
`handle_connection_closed` can be wired as `ConnectionManager`'s `on_connection_closed` hook —
`close_connection` closes the circle the other way (`DeviceSessionManager` asks
`ConnectionManager` to close a specific socket when superseding a duplicate terminal,
ADR-808-8) via a bound-method callback resolved at call time, not construction time, so the
two can be built in either order without a real circular dependency.

**`_handle_frame` (Phase 9.3) replaces Phase 9.1's log-only default `on_frame`** with a real
`PacketParser` call — still no dispatch to any handler (none exist yet, `src/dispatcher/`/
`src/handlers/` remain unbuilt): a successfully parsed `InboundMessage`'s key fields are
logged; a `ProtocolError` (checksum/malformed/unescape failure) is logged and the frame
dropped, never crashing the connection (Backend LLD §6). A `None` result means the frame was
a non-final subpackage still awaiting the rest (`protocol/reassembly.py`).

Framework-agnostic composition root — no FastAPI, no HTTP, no SQLAlchemy
(`.claude/rules/architecture.md` #2: "FastAPI never terminates a device socket").
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone

from src.config import ServerConfig
from src.connection.manager import ConnectionManager
from src.logging_setup import configure_logging, get_logger, log_with_fields
from src.protocol.exceptions import ProtocolError
from src.protocol.parser import PacketParser
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.session.registry import SessionRegistry

logger = get_logger("jt808.server")


class Jt808Server:
    def __init__(self, config: ServerConfig | None = None) -> None:
        self._config = config or ServerConfig.from_env()
        self._sessions = SessionRegistry()
        self._device_session_registry = DeviceSessionRegistry()
        self._device_sessions = DeviceSessionManager(
            registry=self._device_session_registry,
            close_connection=self._close_connection,
        )
        self._parser = PacketParser()
        self._manager = ConnectionManager(
            session_registry=self._sessions,
            read_chunk_size=self._config.read_chunk_size,
            max_frame_size=self._config.max_frame_size,
            idle_timeout_seconds=self._config.idle_timeout_seconds,
            sweep_interval_seconds=self._config.sweep_interval_seconds,
            on_frame=self._handle_frame,
            on_connection_closed=self._device_sessions.handle_connection_closed,
        )
        self._server: asyncio.base_events.Server | None = None

    async def _close_connection(self, connection_id: str, reason: str) -> None:
        await self._manager.close_connection(connection_id, reason=reason)

    async def _handle_frame(self, connection_id: str, frame: bytes) -> None:
        try:
            message = self._parser.parse(frame, received_at=datetime.now(timezone.utc))
        except ProtocolError as exc:
            log_with_fields(
                logger,
                30,
                "frame_parse_error",
                connection_id=connection_id,
                error=str(exc),
            )
            return
        if message is None:
            log_with_fields(
                logger, 10, "frame_awaiting_subpackages", connection_id=connection_id
            )
            return
        log_with_fields(
            logger,
            20,
            "message_parsed",
            connection_id=connection_id,
            message_id=f"0x{message.message_id:04x}",
            terminal_id=message.terminal_id,
            serial_no=message.serial_no,
            body_length=len(message.body),
            encryption_method=message.encryption_method,
        )

    @property
    def parser(self) -> PacketParser:
        return self._parser

    @property
    def manager(self) -> ConnectionManager:
        return self._manager

    @property
    def device_sessions(self) -> DeviceSessionManager:
        """Public entry point a future phase's `AuthHandler` (not built yet) calls
        `.create(...)` on, once packet parsing/dispatch exist."""
        return self._device_sessions

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    @property
    def device_session_count(self) -> int:
        return self._device_sessions.session_count

    @property
    def bound_port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("Server is not started.")
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._manager.handle_client, host=self._config.host, port=self._config.port
        )
        self._manager.start_sweep()
        self._device_sessions.start_sweep(
            timeout_seconds=self._config.device_session_timeout_seconds,
            interval_seconds=self._config.device_session_sweep_interval_seconds,
        )
        sockets = ", ".join(
            str(sock.getsockname()) for sock in self._server.sockets or []
        )
        log_with_fields(logger, 20, "server_started", listening_on=sockets)

    async def stop(self) -> None:
        log_with_fields(
            logger,
            20,
            "server_stopping",
            active_connections=self._manager.connection_count,
            active_device_sessions=self._device_sessions.session_count,
        )
        await self._manager.shutdown()
        await self._device_sessions.shutdown()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        log_with_fields(logger, 20, "server_stopped")

    async def serve_forever(self) -> None:
        await self.start()
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _handle_signal() -> None:
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except NotImplementedError:
                pass  # Windows: add_signal_handler isn't supported for these signals

        await stop_event.wait()
        await self.stop()


async def main() -> None:
    configure_logging(level=logging.INFO)
    server = Jt808Server()
    await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
