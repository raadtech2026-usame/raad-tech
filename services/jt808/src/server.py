"""JT808 TCP transport service entrypoint (Phase 9.1 Transport Layer + Phase 9.2 Session
Management + Phase 9.3 Packet Parser + Phase 9.4 Message Dispatcher + Phase 9.5 Authentication
& Registration + Phase 9.6 Position Pipeline; Phase 2 §5.1, Phase 3.4 §2/§4/§5/§6/§7/§8/§10).
Wires config, logging, the transport-level `SessionRegistry`/`ConnectionManager`, the
device-level `DeviceSessionRegistry`/`DeviceSessionManager`, the `PacketParser`, and the
`MessageDispatcher` (with its `HandlerRegistry` of registration/auth/position handlers plus
placeholders for everything else) into a running `asyncio.start_server`; handles SIGINT/SIGTERM
for graceful shutdown (close every connection, close every device session, stop both sweep
tasks, stop the server) rather than letting the process die with sockets mid-flight.

`DeviceSessionManager` is constructed *before* `ConnectionManager` so its
`handle_connection_closed` can be wired as `ConnectionManager`'s `on_connection_closed` hook —
`close_connection` closes the circle the other way (`DeviceSessionManager` asks
`ConnectionManager` to close a specific socket when superseding a duplicate terminal,
ADR-808-8) via a bound-method callback resolved at call time, not construction time, so the
two can be built in either order without a real circular dependency. The dispatcher's `send`
callback (`_send_frame`) closes an identical circle with `ConnectionManager.send_to_connection`;
`_close_connection` is now shared by *three* callers (`DeviceSessionManager`, `MessageDispatcher`
for handler-requested closes, and nothing else) — one bound method, no duplication.

**`_handle_frame` hands a successfully parsed `InboundMessage` to `MessageDispatcher.dispatch`**
— the "codec -> dispatcher" handoff. A `ProtocolError` (checksum/malformed/unescape failure) is
still logged and the frame dropped *before* the dispatcher ever sees it — malformed packets
never reach dispatch, never crashing the connection (Backend LLD §6). A `None` parse result
(awaiting more subpackages) likewise never reaches the dispatcher.

**`device_provisioning` (Phase 9.5, constructor parameter):** the seam `TerminalRegistrationHandler`/
`TerminalAuthenticationHandler` use to decide accept/reject and verify auth codes
(`handlers/provisioning_port.py` — no concrete implementation exists in this codebase yet).
Defaults to `NullDeviceProvisioningPort`, fail-closed (every registration/auth rejected) —
the same "fail loudly, don't fake it" policy the Business API's own DI container applies to an
unconfigured port, never silently accepting every device. A real implementation is injected
here once one is built (a later phase, with real device-provisioning-workflow access).

**Handlers registered through Phase 9.5:** `TerminalRegistrationHandler` (`0x0100`),
`TerminalAuthenticationHandler` (`0x0102`) — real protocol behavior.

**Handlers registered this phase (9.6):** `LocationHandler` (`0x0200`), `BulkLocationHandler`
(`0x0704`) — parse the position body, resolve device/vehicle/org identity from the terminal's
`DeviceSession`, and publish `DevicePositionReported` via `event_publisher` (below). Neither
calls `TrackingApplicationService` or imports `tracking` — see `handlers/location_handler.py`'s
module docstring for the conflict this resolved and why. Every other named `message_id` still
resolves to a no-op `PlaceholderMessageHandler` (`dispatcher/placeholder_handler.py`'s module
docstring) — Heartbeat/Alarm/CommandAck/Logout business logic remains a later phase's job.

**`event_publisher` (Phase 9.6, constructor parameter):** the port `LocationHandler`/
`BulkLocationHandler` use to publish `DevicePositionReported` (`events/publisher_port.py` — no
real broker/outbox implementation exists in this codebase yet, since no broker technology is
approved anywhere in this repo). Defaults to `LoggingEventPublisher` — publishing degrades to a
structured log line, never a crash. A real outbox+broker implementation is injected here once
one is built (a later phase, once a broker dependency is proposed and approved per `.claude/
rules/workflow.md` #1/#2).

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
from src.dispatcher import message_ids
from src.dispatcher.dispatcher import MessageDispatcher
from src.dispatcher.placeholder_handler import PlaceholderMessageHandler
from src.dispatcher.registry import HandlerRegistry
from src.dispatcher.unknown_handler import UnknownMessageHandler
from src.events.publisher_port import EventPublisher, LoggingEventPublisher
from src.handlers.authentication_handler import TerminalAuthenticationHandler
from src.handlers.bulk_location_handler import BulkLocationHandler
from src.handlers.location_handler import LocationHandler
from src.handlers.provisioning_port import (
    DeviceProvisioningPort,
    NullDeviceProvisioningPort,
)
from src.handlers.registration_handler import TerminalRegistrationHandler
from src.logging_setup import configure_logging, get_logger, log_with_fields
from src.protocol.exceptions import ProtocolError
from src.protocol.parser import PacketParser
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.session.registry import SessionRegistry

logger = get_logger("jt808.server")

# JT808 Technical Design §7/§8's named handler set that stays a placeholder this phase — see
# dispatcher/message_ids.py's module docstring for the per-message-ID primary-spec citation.
# REGISTRATION, AUTHENTICATION, LOCATION_REPORT, and BULK_LOCATION_REPORT are deliberately
# absent: they get real handlers below.
_PLACEHOLDER_HANDLER_NAMES = {
    message_ids.TERMINAL_GENERAL_RESPONSE: "CommandAck",
    message_ids.HEARTBEAT: "Heartbeat",
    message_ids.LOGOUT: "Logout",
    message_ids.MULTIMEDIA_EVENT_UPLOAD: "Alarm",
}


class Jt808Server:
    def __init__(
        self,
        config: ServerConfig | None = None,
        *,
        device_provisioning: DeviceProvisioningPort | None = None,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._config = config or ServerConfig.from_env()
        self._device_provisioning = device_provisioning or NullDeviceProvisioningPort()
        self._event_publisher = event_publisher or LoggingEventPublisher()
        self._sessions = SessionRegistry()
        self._device_session_registry = DeviceSessionRegistry()
        self._device_sessions = DeviceSessionManager(
            registry=self._device_session_registry,
            close_connection=self._close_connection,
        )
        self._parser = PacketParser()

        self._handler_registry = HandlerRegistry()
        for handler_message_id, name in _PLACEHOLDER_HANDLER_NAMES.items():
            self._handler_registry.register(
                handler_message_id, PlaceholderMessageHandler(name)
            )
        self._handler_registry.register(
            message_ids.REGISTRATION,
            TerminalRegistrationHandler(self._device_provisioning),
        )
        self._handler_registry.register(
            message_ids.AUTHENTICATION,
            TerminalAuthenticationHandler(self._device_provisioning),
        )
        self._handler_registry.register(
            message_ids.LOCATION_REPORT,
            LocationHandler(self._event_publisher),
        )
        self._handler_registry.register(
            message_ids.BULK_LOCATION_REPORT,
            BulkLocationHandler(self._event_publisher),
        )
        self._dispatcher = MessageDispatcher(
            registry=self._handler_registry,
            unknown_handler=UnknownMessageHandler(),
            device_sessions=self._device_sessions,
            send=self._send_frame,
            close_connection=self._close_connection,
        )

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

    async def _send_frame(self, connection_id: str, data: bytes) -> None:
        await self._manager.send_to_connection(connection_id, data)

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
        await self._dispatcher.dispatch(connection_id, message)

    @property
    def parser(self) -> PacketParser:
        return self._parser

    @property
    def dispatcher(self) -> MessageDispatcher:
        return self._dispatcher

    @property
    def handler_registry(self) -> HandlerRegistry:
        return self._handler_registry

    @property
    def manager(self) -> ConnectionManager:
        return self._manager

    @property
    def device_sessions(self) -> DeviceSessionManager:
        """`.create(...)` is called by `TerminalAuthenticationHandler` on successful
        authentication (Phase 9.5) — exposed publicly mainly for tests/manual verification to
        assert on session state directly."""
        return self._device_sessions

    @property
    def device_provisioning(self) -> DeviceProvisioningPort:
        return self._device_provisioning

    @property
    def event_publisher(self) -> EventPublisher:
        return self._event_publisher

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
