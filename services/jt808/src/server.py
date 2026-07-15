"""JT808 TCP transport service entrypoint (Phase 9.1 — Transport Layer only; Phase 2 §5.1,
Phase 3.4 §2). Wires config, logging, `SessionRegistry`, and `ConnectionManager` into a
running `asyncio.start_server`; handles SIGINT/SIGTERM for graceful shutdown (close every
connection, stop the sweep task, stop the server) rather than letting the process die with
sockets mid-flight.

Framework-agnostic composition root — no FastAPI, no HTTP, no SQLAlchemy
(`.claude/rules/architecture.md` #2: "FastAPI never terminates a device socket").
"""

from __future__ import annotations

import asyncio
import logging
import signal

from src.config import ServerConfig
from src.connection.manager import ConnectionManager
from src.logging_setup import configure_logging, get_logger, log_with_fields
from src.session.registry import SessionRegistry

logger = get_logger("jt808.server")


class Jt808Server:
    def __init__(self, config: ServerConfig | None = None) -> None:
        self._config = config or ServerConfig.from_env()
        self._sessions = SessionRegistry()
        self._manager = ConnectionManager(
            session_registry=self._sessions,
            read_chunk_size=self._config.read_chunk_size,
            max_frame_size=self._config.max_frame_size,
            idle_timeout_seconds=self._config.idle_timeout_seconds,
            sweep_interval_seconds=self._config.sweep_interval_seconds,
        )
        self._server: asyncio.base_events.Server | None = None

    @property
    def manager(self) -> ConnectionManager:
        return self._manager

    @property
    def session_count(self) -> int:
        return len(self._sessions)

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
        )
        await self._manager.shutdown()
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
