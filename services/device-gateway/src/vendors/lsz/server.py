"""LSZ MDVR TCP transport service entrypoint (ADR-0009; roadmap tracks B1/B2). Wires this
vendor's own protocol/dispatcher/handlers stack onto the shared, vendor-agnostic `connection`/
`session`/`events` layers — the concrete proof that ADR-0009's "only the protocol adapter
differs" claim holds in code, not just in the architecture record. Implements the common
`DeviceProtocolAdapter` interface (`src/adapter.py`) so `src/gateway.py`'s composition root can
start/stop it alongside `vendors.jt808.server.Jt808Server` without knowing anything vendor-
specific about either.

Structurally mirrors `vendors.jt808.server.Jt808Server` closely (same signal handling, same
start/stop/serve_forever shape, same "malformed frame logged and dropped before dispatch"
behavior) — kept as a separate class rather than a shared base, since the two servers'
constructors wire genuinely different handler sets and neither is a strict subset of the other;
a shared base class would buy little beyond what `DeviceProtocolAdapter` plus the already-shared
`ConnectionManager`/`DeviceSessionManager` already provide.

**Video/media-channel support is out of scope here** — this server only ever accepts signaling-
channel connections (registration/heartbeat/position). The vendor's separate media-channel
protocol (live video, file transfer, firmware upgrade) is tracked under roadmap track B3, not
built by this module.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone

from src.adapter import DeviceProtocolAdapter
from src.connection.manager import ConnectionManager
from src.events.device_offline import DeviceOffline
from src.events.device_online import DeviceOnline
from src.events.publisher_port import EventPublisher, LoggingEventPublisher
from src.latest_position.writer_port import LatestPositionWriter, LoggingLatestPositionWriter
from src.logging_setup import configure_logging, get_logger, log_with_fields
from src.session.device_session import DeviceSession
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.session.registry import SessionRegistry
from src.vendors.lsz.config import MdvrServerConfig
from src.vendors.lsz.dispatcher.dispatcher import MdvrMessageDispatcher
from src.vendors.lsz.dispatcher.registry import MdvrHandlerRegistry
from src.vendors.lsz.handlers.heartbeat_handler import MdvrHeartbeatHandler
from src.vendors.lsz.handlers.position_handler import MdvrPositionHandler
from src.vendors.lsz.handlers.provisioning_port import (
    MdvrDeviceProvisioningPort,
    NullMdvrDeviceProvisioningPort,
)
from src.vendors.lsz.handlers.registration_handler import MdvrRegistrationHandler
from src.vendors.lsz.protocol.exceptions import MdvrProtocolError
from src.vendors.lsz.protocol.framing import MdvrFrameBuffer
from src.vendors.lsz.protocol.parser import parse_frame

logger = get_logger("mdvr.server")

_REGISTRATION_KEYWORD = "V101"
_HEARTBEAT_KEYWORD = "V109"
_POSITION_REPORT_KEYWORD = "V114"


class MdvrServer(DeviceProtocolAdapter):
    def __init__(
        self,
        config: MdvrServerConfig | None = None,
        *,
        device_provisioning: MdvrDeviceProvisioningPort | None = None,
        event_publisher: EventPublisher | None = None,
        latest_position_writer: LatestPositionWriter | None = None,
    ) -> None:
        self._config = config or MdvrServerConfig.from_env()
        self._device_provisioning = device_provisioning or NullMdvrDeviceProvisioningPort()
        self._event_publisher = event_publisher or LoggingEventPublisher()
        self._latest_position_writer = latest_position_writer or LoggingLatestPositionWriter()
        self._sessions = SessionRegistry()
        self._device_session_registry = DeviceSessionRegistry()
        self._device_sessions = DeviceSessionManager(
            registry=self._device_session_registry,
            close_connection=self._close_connection,
            on_device_online=self._on_device_online,
            on_device_offline=self._on_device_offline,
        )

        self._handler_registry = MdvrHandlerRegistry()
        self._handler_registry.register(
            _REGISTRATION_KEYWORD, MdvrRegistrationHandler(self._device_provisioning)
        )
        self._handler_registry.register(_HEARTBEAT_KEYWORD, MdvrHeartbeatHandler())
        self._handler_registry.register(
            _POSITION_REPORT_KEYWORD,
            MdvrPositionHandler(
                self._event_publisher,
                latest_position_writer=self._latest_position_writer,
            ),
        )
        self._dispatcher = MdvrMessageDispatcher(
            registry=self._handler_registry,
            device_sessions=self._device_sessions,
            send=self._send_frame,
            close_connection=self._close_connection,
        )

        self._manager = ConnectionManager(
            session_registry=self._sessions,
            read_chunk_size=self._config.read_chunk_size,
            idle_timeout_seconds=self._config.idle_timeout_seconds,
            sweep_interval_seconds=self._config.sweep_interval_seconds,
            on_frame=self._handle_frame,
            on_connection_closed=self._device_sessions.handle_connection_closed,
            frame_buffer_factory=lambda: MdvrFrameBuffer(
                max_frame_size=self._config.max_frame_size
            ),
        )
        self._server: asyncio.base_events.Server | None = None

    async def _close_connection(self, connection_id: str, reason: str) -> None:
        await self._manager.close_connection(connection_id, reason=reason)

    async def _send_frame(self, connection_id: str, data: bytes) -> None:
        await self._manager.send_to_connection(connection_id, data)

    async def _on_device_online(self, session: DeviceSession) -> None:
        """Wired into `DeviceSessionManager` (device-gateway Redis integration): the first
        `V109` heartbeat after registration promotes `AUTHENTICATED -> ONLINE`
        (`MdvrHeartbeatHandler` -> `touch()`), which fires this, publishing a real `DeviceOnline`
        event rather than only logging one."""
        now = datetime.now(timezone.utc)
        log_with_fields(logger, 20, "device_online", terminal_id=session.terminal_id)
        await self._event_publisher.publish(
            DeviceOnline(
                terminal_id=session.terminal_id,
                organization_id=session.organization_id,
                vehicle_id=session.vehicle_id,
                device_id=session.device_id,
                event_time=now,
                received_at=now,
            )
        )

    async def _on_device_offline(self, session: DeviceSession, reason: str) -> None:
        now = datetime.now(timezone.utc)
        log_with_fields(
            logger, 20, "device_offline", terminal_id=session.terminal_id, reason=reason
        )
        await self._event_publisher.publish(
            DeviceOffline(
                terminal_id=session.terminal_id,
                organization_id=session.organization_id,
                vehicle_id=session.vehicle_id,
                device_id=session.device_id,
                reason=reason,
                event_time=now,
                received_at=now,
            )
        )

    async def _handle_frame(self, connection_id: str, frame: bytes) -> None:
        try:
            message = parse_frame(frame, received_at=datetime.now(timezone.utc))
        except MdvrProtocolError as exc:
            log_with_fields(
                logger,
                30,
                "frame_parse_error",
                connection_id=connection_id,
                error=str(exc),
            )
            return
        log_with_fields(
            logger,
            20,
            "message_parsed",
            connection_id=connection_id,
            keyword=message.keyword,
            device_serial_number=message.device_serial_number,
        )
        await self._dispatcher.dispatch(connection_id, message)

    @property
    def name(self) -> str:
        return "lsz"

    @property
    def handler_registry(self) -> MdvrHandlerRegistry:
        return self._handler_registry

    @property
    def manager(self) -> ConnectionManager:
        return self._manager

    @property
    def device_sessions(self) -> DeviceSessionManager:
        return self._device_sessions

    @property
    def device_provisioning(self) -> MdvrDeviceProvisioningPort:
        return self._device_provisioning

    @property
    def event_publisher(self) -> EventPublisher:
        return self._event_publisher

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    async def device_session_count(self) -> int:
        return await self._device_sessions.session_count()

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
            active_device_sessions=await self._device_sessions.session_count(),
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
    server = MdvrServer()
    await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
