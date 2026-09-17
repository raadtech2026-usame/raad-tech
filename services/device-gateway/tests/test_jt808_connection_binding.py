"""C8 regression tests (2026-09-17, security and correctness): a JT/T 808 session is usable only
on the connection that authenticated it, and only while this process holds that connection open.

Before this fix every inbound handler resolved the session by terminal ID alone, so:

- any socket presenting a terminal ID could submit GPS positions, bulk positions and A/V
  capability reports under another connection's authenticated session, and keep that session
  alive with heartbeats;
- a session left in Redis by a previous gateway process stayed usable by a new, unauthenticated
  connection, and platform commands were "sent" to its long-gone socket.

Scenarios, matching the requested regression list: (a) valid authenticated connection,
(b) unauthenticated connection, (c) stale session after a gateway restart, (d) same terminal ID on
a new connection, (e) disconnected old socket, (f) concurrent/reconnecting sessions. Covered at
handler level, over real loopback TCP against `Jt808Server`, and through `DeviceGateway` with the
Redis-backed session registry.
"""

import asyncio
import json
import unittest
from datetime import datetime, timezone

from src.broker_config import BrokerConfig
from src.cache_config import CacheConfig
from src.events.device_av_attributes_reported import DeviceAvAttributesReported
from src.events.device_command_result import DeviceCommandResult
from src.events.device_offline import DeviceOffline
from src.gateway import DeviceGateway
from src.session.device_session import DeviceConnectivityState, DeviceSession
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.session.redis_device_session_registry import RedisDeviceSessionRegistry
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.config import ServerConfig
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.dispatcher.handler import HandlerContext
from src.vendors.jt808.handlers.av_attributes_handler import AvAttributesHandler
from src.vendors.jt808.handlers.bulk_location_handler import BulkLocationHandler
from src.vendors.jt808.handlers.heartbeat_handler import HeartbeatHandler
from src.vendors.jt808.handlers.location_handler import LocationHandler
from src.vendors.jt808.protocol.framing import FrameBuffer
from src.vendors.jt808.protocol.message import InboundMessage
from src.vendors.jt808.protocol.parser import PacketParser
from src.vendors.jt808.server import Jt808Server
from src.vendors.lsz.config import MdvrServerConfig as LszConfig
from tests.test_av_attributes_handler import _report_body
from tests.test_gateway import FakeRedis, _device_registered_entries, _wire_frame
from tests.test_position_body import _build_body
from tests.test_position_pipeline_integration import (
    AUTH_CODE,
    GrantingProvisioningPort,
    RecordingEventPublisher,
    auth_body,
    bulk_body,
)

PHONE = "00000000013800138000"


async def _noop_close(connection_id: str, reason: str) -> None:
    return None


def _message(message_id: int, body: bytes = b"", serial_no: int = 1) -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        terminal_id=PHONE,
        serial_no=serial_no,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


def _general_response_result(handler_result) -> int:
    return handler_result.response_body[4]


class HandlerConnectionBindingTests(unittest.IsolatedAsyncioTestCase):
    """The terminal is authenticated on `conn-real`; `conn-intruder` is an open socket presenting
    the same terminal ID without authenticating (b, d, f)."""

    async def asyncSetUp(self) -> None:
        self.open_connections = {"conn-real", "conn-intruder"}
        self.sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(),
            close_connection=_noop_close,
            is_connection_open=lambda cid: cid in self.open_connections,
        )
        await self.sessions.create(
            connection_id="conn-real",
            terminal_id=PHONE,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        self.publisher = RecordingEventPublisher()

    def _context(self, connection_id: str) -> HandlerContext:
        return HandlerContext(connection_id=connection_id, device_sessions=self.sessions)

    async def _session(self) -> DeviceSession:
        return await self.sessions.resolve(PHONE)

    async def test_a_location_from_the_authenticated_connection_is_accepted(self) -> None:
        result = await LocationHandler(self.publisher).handle(
            _message(message_ids.LOCATION_REPORT, _build_body()), self._context("conn-real")
        )

        self.assertEqual(_general_response_result(result), 0)
        self.assertEqual(len(self.publisher.positions), 1)
        self.assertEqual((await self._session()).state, DeviceConnectivityState.ONLINE)

    async def test_b_location_from_another_connection_is_refused_and_does_not_touch(self) -> None:
        result = await LocationHandler(self.publisher).handle(
            _message(message_ids.LOCATION_REPORT, _build_body()), self._context("conn-intruder")
        )

        self.assertEqual(_general_response_result(result), 1)  # failure
        self.assertEqual(self.publisher.published, [])
        self.assertEqual((await self._session()).state, DeviceConnectivityState.AUTHENTICATED)

    async def test_b_bulk_location_from_another_connection_is_refused(self) -> None:
        result = await BulkLocationHandler(self.publisher).handle(
            _message(message_ids.BULK_LOCATION_REPORT, bulk_body([_build_body()])),
            self._context("conn-intruder"),
        )

        self.assertEqual(_general_response_result(result), 1)
        self.assertEqual(self.publisher.published, [])

    async def test_b_camera_discovery_report_from_another_connection_is_dropped(self) -> None:
        """A forged `0x1003` would otherwise register cameras on the real device's record."""
        result = await AvAttributesHandler(PendingCommandTracker(), self.publisher).handle(
            _message(
                message_ids.AV_ATTRIBUTES_REPORT,
                _report_body(max_audio_channels=1, max_video_channels=8),
            ),
            self._context("conn-intruder"),
        )

        self.assertIsNone(result.response_message_id)
        self.assertFalse(
            any(isinstance(e, DeviceAvAttributesReported) for e in self.publisher.published)
        )

    async def test_a_camera_discovery_report_from_the_authenticated_connection_is_published(
        self,
    ) -> None:
        await AvAttributesHandler(PendingCommandTracker(), self.publisher).handle(
            _message(
                message_ids.AV_ATTRIBUTES_REPORT,
                _report_body(max_audio_channels=1, max_video_channels=4),
            ),
            self._context("conn-real"),
        )

        reports = [e for e in self.publisher.published if isinstance(e, DeviceAvAttributesReported)]
        self.assertEqual([r.max_video_channels for r in reports], [4])

    async def test_b_heartbeat_from_another_connection_cannot_keep_the_session_alive(self) -> None:
        session_before = await self._session()
        last_seen_before = session_before.last_seen_at

        await HeartbeatHandler().handle(
            _message(message_ids.HEARTBEAT), self._context("conn-intruder")
        )

        session_after = await self._session()
        self.assertEqual(session_after.last_seen_at, last_seen_before)
        self.assertEqual(session_after.state, DeviceConnectivityState.AUTHENTICATED)

    async def test_e_location_on_the_sessions_own_connection_after_it_closed_is_refused(
        self,
    ) -> None:
        self.open_connections.discard("conn-real")

        result = await LocationHandler(self.publisher).handle(
            _message(message_ids.LOCATION_REPORT, _build_body()), self._context("conn-real")
        )

        self.assertEqual(_general_response_result(result), 1)
        self.assertEqual(self.publisher.published, [])


class _Socket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self._frames = FrameBuffer(max_frame_size=8192)
        self._pending: list[bytes] = []

    async def send(self, message_id: int, serial_no: int, body: bytes = b"") -> None:
        self.writer.write(_wire_frame(message_id, self.phone, serial_no, body=body))
        await self.writer.drain()

    async def receive(self, timeout: float = 2.0):
        """The next frame the platform sent, or `None` once the platform closed the socket."""
        while not self._pending:
            chunk = await asyncio.wait_for(self.reader.read(512), timeout=timeout)
            if not chunk:
                return None
            self._pending.extend(self._frames.feed(chunk))
        return PacketParser().parse(self._pending.pop(0), received_at=datetime.now(timezone.utc))

    phone = PHONE


class Jt808ServerConnectionBindingTests(unittest.IsolatedAsyncioTestCase):
    """Over real loopback TCP against `Jt808Server`, with the production connection manager
    supplying connection liveness."""

    async def asyncSetUp(self) -> None:
        self.registry = DeviceSessionRegistry()
        self.publisher = RecordingEventPublisher()
        self.server = Jt808Server(
            ServerConfig(host="127.0.0.1", port=0),
            device_provisioning=GrantingProvisioningPort(),
            event_publisher=self.publisher,
            device_session_registry=self.registry,
        )
        self._sockets: list[_Socket] = []

    async def asyncTearDown(self) -> None:
        for sock in self._sockets:
            if not sock.writer.is_closing():
                sock.writer.close()
        await self.server.stop()

    async def _connect(self) -> _Socket:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        sock = _Socket(reader, writer)
        self._sockets.append(sock)
        return sock

    async def _authenticate(self, sock: _Socket, serial_no: int = 1) -> None:
        await sock.send(message_ids.AUTHENTICATION, serial_no, auth_body(AUTH_CODE))
        response = await sock.receive()
        self.assertEqual((response.message_id, response.body[4]), (0x8001, 0))

    async def _report_position(self, sock: _Socket, serial_no: int) -> int | None:
        """Sends a `0x0200` and returns the result code of its `0x8001`, or `None` if the
        platform closed the socket instead."""
        await sock.send(message_ids.LOCATION_REPORT, serial_no, _build_body())
        ack = await sock.receive()
        if ack is None:
            return None
        self.assertEqual(int.from_bytes(ack.body[0:2], "big"), serial_no)
        return ack.body[4]

    def _command_results(self) -> list[DeviceCommandResult]:
        return [e for e in self.publisher.published if isinstance(e, DeviceCommandResult)]

    async def test_a_b_f_unauthenticated_concurrent_connection_cannot_report_for_the_device(
        self,
    ) -> None:
        await self.server.start()
        real = await self._connect()
        await self._authenticate(real)
        intruder = await self._connect()  # open alongside, same terminal ID, never authenticates

        self.assertEqual(await self._report_position(intruder, 7), 1)  # (b) refused
        self.assertEqual(await self._report_position(real, 8), 0)  # (a) accepted
        self.assertEqual(await self._report_position(intruder, 9), 1)  # (f) still refused

        self.assertEqual(len(self.publisher.positions), 1)
        self.assertEqual(self.server.manager.connection_count, 2)  # refusal closes nothing

    async def test_d_f_reauthenticating_on_a_new_connection_retires_the_old_one(self) -> None:
        await self.server.start()
        old = await self._connect()
        await self._authenticate(old)
        new = await self._connect()
        await self._authenticate(new)  # same terminal, new connection

        self.assertIsNone(await old.receive())  # the platform closed the superseded socket
        self.assertEqual(await self._report_position(new, 5), 0)

        self.assertTrue(
            await self.server.command_sender.send(
                terminal_id=PHONE,
                message_id=message_ids.QUERY_AV_ATTRIBUTES,
                body=b"",
                correlation_id="corr-after-reconnect",
            )
        )
        command = await new.receive()
        self.assertEqual(command.message_id, message_ids.QUERY_AV_ATTRIBUTES)

    async def test_e_disconnected_socket_receives_no_command_and_is_reported_offline(self) -> None:
        await self.server.start()
        sock = await self._connect()
        await self._authenticate(sock)
        sock.writer.close()
        for _ in range(50):  # wait for the server to observe the disconnect
            if self.server.manager.connection_count == 0:
                break
            await asyncio.sleep(0.02)

        sent = await self.server.command_sender.send(
            terminal_id=PHONE,
            message_id=message_ids.QUERY_AV_ATTRIBUTES,
            body=b"",
            correlation_id="corr-disconnected",
        )

        self.assertFalse(sent)
        self.assertEqual(
            [(r.correlation_id, r.reason) for r in self._command_results()],
            [("corr-disconnected", "device_offline")],
        )
        self.assertIsNone(await self.registry.get(PHONE))

    async def test_c_stale_session_from_a_previous_process_is_closed_at_startup_and_unusable(
        self,
    ) -> None:
        await self.registry.add_exclusive(
            DeviceSession(
                terminal_id=PHONE,
                connection_id="conn-previous-process",
                device_id="device-1",
                vehicle_id="vehicle-1",
                organization_id="org-1",
                state=DeviceConnectivityState.ONLINE,
            )
        )

        await self.server.start()

        self.assertIsNone(await self.registry.get(PHONE))
        offline = [e for e in self.publisher.published if isinstance(e, DeviceOffline)]
        self.assertEqual([(e.terminal_id, e.reason) for e in offline], [(PHONE, "connection_lost")])

        newcomer = await self._connect()  # presents the terminal ID without authenticating
        self.assertEqual(await self._report_position(newcomer, 3), 1)
        self.assertEqual(self.publisher.positions, [])
        self.assertFalse(
            await self.server.command_sender.send(
                terminal_id=PHONE,
                message_id=message_ids.QUERY_AV_ATTRIBUTES,
                body=b"",
                correlation_id="corr-stale",
            )
        )
        self.assertEqual(self._command_results()[-1].reason, "device_offline")

        await self._authenticate(newcomer, serial_no=4)  # a real authentication still works
        self.assertEqual(await self._report_position(newcomer, 5), 0)


class RedisSessionRegistryRestartTests(unittest.IsolatedAsyncioTestCase):
    """(c) through `DeviceGateway` with the Redis-backed session registry — the production wiring
    whenever a broker is configured — simulating a restart: the session is written to Redis
    exactly as the previous process wrote it, then a fresh gateway starts against that data."""

    TERMINAL = "00000000014482607571"

    async def test_c_stale_redis_session_is_closed_on_restart_and_cannot_be_used(self) -> None:
        redis = FakeRedis()
        redis.entries.extend(
            _device_registered_entries(
                terminal_id=self.TERMINAL,
                serial_number="00007",
                device_id="device-1",
                vehicle_id="vehicle-1",
                org_id="org-1",
            )
        )
        redis._next_id = 4
        await RedisDeviceSessionRegistry(redis).add_exclusive(
            DeviceSession(
                terminal_id=self.TERMINAL,
                connection_id="conn-from-the-previous-process",
                device_id="device-1",
                vehicle_id="vehicle-1",
                organization_id="org-1",
                state=DeviceConnectivityState.ONLINE,
            )
        )
        self.assertIsNotNone(await redis.get(f"device_session:{self.TERMINAL}"))

        gateway = DeviceGateway(
            broker_config=BrokerConfig(),
            cache_config=CacheConfig(),
            redis_client=redis,
            cache_redis_client=redis,
            jt808_config=ServerConfig(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        await gateway.start()
        writer = None
        try:
            self.assertIsNone(await redis.get(f"device_session:{self.TERMINAL}"))
            offline = [
                json.loads(fields["data"])
                for _, fields in redis.entries
                if json.loads(fields["data"])["event_type"] == "DeviceOffline"
            ]
            self.assertEqual(len(offline), 1)
            self.assertEqual(offline[0]["payload"]["reason"], "connection_lost")

            reader, writer = await asyncio.open_connection(
                "127.0.0.1", gateway.adapter("jt808").bound_port
            )
            sock = _Socket(reader, writer)
            sock.phone = self.TERMINAL
            await sock.send(message_ids.LOCATION_REPORT, 1, _build_body())
            ack = await sock.receive()

            self.assertEqual(ack.body[4], 1)  # refused: no authentication on this connection
            events = [json.loads(fields["data"])["event_type"] for _, fields in redis.entries]
            self.assertNotIn("DevicePositionReported", events)
            self.assertIsNone(await redis.get("vehicle:vehicle-1:last"))
        finally:
            if writer is not None:
                writer.close()
            await gateway.stop()


if __name__ == "__main__":
    unittest.main()
