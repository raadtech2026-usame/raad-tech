"""`ViewerServer` integration tests — D5-critical: real loopback TCP/WS handshake, proving a
viewer with no valid token can never reach `hub.add_viewer` (no FLV byte, ever), and that a valid
token is honored exactly once.
"""

import asyncio
import struct
import unittest
from unittest.mock import patch

from src.events.publisher_port import LoggingSessionEventPublisher
from src.session.session_manager import SessionManager
from src.session.uplink_registry import IngestConnectionRegistry
from src.session.video_session import VideoSessionKind
from src.session.viewer_token import InMemorySingleUseTokenGuard, mint_token
from src.viewer.broadcast_hub import SessionBroadcastHub
from src.viewer.viewer_server import ViewerServer

SECRET = b"test-secret"


async def _ws_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, token: str | None) -> None:
    import base64, os

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    path = f"/viewer?token={token}" if token else "/viewer"
    request = (
        f"GET {path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    writer.write(request.encode("ascii"))
    await writer.drain()
    status_line = (await reader.readline()).decode("iso-8859-1")
    assert "101" in status_line, status_line
    while True:
        line = (await reader.readline()).decode("iso-8859-1").strip()
        if not line:
            break


async def _send_ws_binary_frame(writer: asyncio.StreamWriter, payload: bytes) -> None:
    """Client-side (masked, RFC 6455 §5.3) binary frame — only ADR-0036's own uplink test needs
    this; every pre-existing test in this file only ever *reads* frames."""
    import os

    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    header = bytes([0x80 | 0x2])  # FIN=1, opcode=binary
    length = len(masked)
    if length <= 125:
        header += bytes([0x80 | length])
    else:
        header += bytes([0x80 | 126]) + struct.pack("!H", length)
    writer.write(header + mask + masked)
    await writer.drain()


async def _read_ws_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first_two = await reader.readexactly(2)
    opcode = first_two[0] & 0x0F
    length = first_two[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    payload = await reader.readexactly(length) if length else b""
    return opcode, payload


class ViewerServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.session_manager = SessionManager(event_publisher=LoggingSessionEventPublisher())
        self.token_guard = InMemorySingleUseTokenGuard()
        self.hubs: dict[str, SessionBroadcastHub] = {}
        self.server = ViewerServer(
            host="127.0.0.1",
            port=0,
            secret=SECRET,
            token_guard=self.token_guard,
            session_manager=self.session_manager,
            hubs=self.hubs,
        )
        await self.server.start()

    async def asyncTearDown(self) -> None:
        await self.server.stop()

    async def test_a_valid_token_for_an_active_session_receives_the_flv_header(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
        )
        self.hubs[session.session_id] = SessionBroadcastHub(session.session_id)
        token = mint_token(session_id=session.session_id, secret=SECRET, ttl_seconds=30)

        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader, writer, token=token)

        opcode, payload = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
        self.assertEqual(payload[0:3], b"FLV")
        await asyncio.sleep(0.05)
        self.assertEqual(session.viewer_count, 1)
        writer.close()

    async def test_missing_token_is_rejected_with_close_and_no_flv_bytes(self) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader, writer, token=None)

        opcode, payload = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
        self.assertEqual(opcode, 0x8)  # close
        code = struct.unpack("!H", payload[0:2])[0]
        self.assertEqual(code, 4001)
        writer.close()

    async def test_forged_token_is_rejected(self) -> None:
        forged = mint_token(session_id="some-session", secret=b"wrong-secret", ttl_seconds=30)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader, writer, token=forged)

        opcode, payload = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
        self.assertEqual(opcode, 0x8)
        self.assertEqual(struct.unpack("!H", payload[0:2])[0], 4001)
        writer.close()

    async def test_token_for_a_session_with_no_hub_is_rejected_as_not_active(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
        )
        # deliberately never registered in self.hubs - session exists but isn't broadcast-ready
        token = mint_token(session_id=session.session_id, secret=SECRET, ttl_seconds=30)

        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader, writer, token=token)

        opcode, payload = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
        self.assertEqual(opcode, 0x8)
        self.assertEqual(struct.unpack("!H", payload[0:2])[0], 4004)
        writer.close()

    async def test_a_reused_token_is_rejected_the_second_time(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
        )
        self.hubs[session.session_id] = SessionBroadcastHub(session.session_id)
        token = mint_token(session_id=session.session_id, secret=SECRET, ttl_seconds=30)

        reader1, writer1 = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader1, writer1, token=token)
        await asyncio.wait_for(_read_ws_frame(reader1), timeout=2.0)  # consumes the FLV header
        writer1.close()

        reader2, writer2 = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader2, writer2, token=token)  # same token again
        opcode, payload = await asyncio.wait_for(_read_ws_frame(reader2), timeout=2.0)
        self.assertEqual(opcode, 0x8)
        self.assertEqual(struct.unpack("!H", payload[0:2])[0], 4001)
        writer2.close()

    async def test_viewer_disconnect_decrements_the_session_viewer_count(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
        )
        self.hubs[session.session_id] = SessionBroadcastHub(session.session_id)
        token = mint_token(session_id=session.session_id, secret=SECRET, ttl_seconds=30)

        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader, writer, token=token)
        await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
        await asyncio.sleep(0.05)
        self.assertEqual(session.viewer_count, 1)

    async def test_viewer_connection_receives_periodic_keepalive_pings(self) -> None:
        """2026-09-02 — regression coverage for the new WS-level keepalive
        (`ViewerServer._ping_loop`/`_pump_with_keepalive`), added while diagnosing a real,
        physically-observed ~32s browser<->relay WebSocket disconnect pattern (see
        `viewer_server.py`'s own `_PING_INTERVAL_SECONDS` docstring for the full evidence). This
        server previously never sent a ping of its own at all - proves it now does, on a real
        loopback socket, without needing to wait out the real (10s) production interval."""
        with patch("src.viewer.viewer_server._PING_INTERVAL_SECONDS", 0.05):
            session = self.session_manager.create_session(
                terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
            )
            self.hubs[session.session_id] = SessionBroadcastHub(session.session_id)
            token = mint_token(session_id=session.session_id, secret=SECRET, ttl_seconds=30)

            reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
            await _ws_handshake(reader, writer, token=token)
            await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)  # the FLV header

            opcode, payload = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
            self.assertEqual(opcode, 0x9)  # PING
            self.assertEqual(payload, b"")

            # A second ping proves this is a genuinely periodic loop, not a one-shot.
            opcode2, _payload2 = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
            self.assertEqual(opcode2, 0x9)
            writer.close()

    async def test_intercom_uplink_connection_also_receives_periodic_keepalive_pings(self) -> None:
        """The same keepalive must apply to the intercom uplink role, not just ordinary viewers -
        both exhibited the identical ~32s disconnect pattern live."""
        with patch("src.viewer.viewer_server._PING_INTERVAL_SECONDS", 0.05):
            session = self.session_manager.create_session(
                terminal_id="T1", kind=VideoSessionKind.INTERCOM, correlation_id="c1",
                logical_channel=1,
            )
            uplink_registry = IngestConnectionRegistry()
            server = ViewerServer(
                host="127.0.0.1", port=0, secret=SECRET, token_guard=self.token_guard,
                session_manager=self.session_manager, hubs=self.hubs,
                uplink_registry=uplink_registry,
            )
            await server.start()
            try:
                token = mint_token(
                    session_id=session.session_id, secret=SECRET, ttl_seconds=30, role="uplink"
                )
                reader, writer = await asyncio.open_connection("127.0.0.1", server.bound_port)
                await _ws_handshake(reader, writer, token=token)

                opcode, _payload = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
                self.assertEqual(opcode, 0x9)  # PING - the uplink role gets no FLV header first
                writer.close()
            finally:
                await server.stop()

        writer.close()
        await asyncio.sleep(0.1)
        self.assertEqual(session.viewer_count, 0)


class UplinkRoleTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0036 — a `role="uplink"` token connects, but is never registered as a broadcast
    viewer, and its own inbound binary frames are forwarded to `IngestConnectionRegistry`
    instead."""

    async def asyncSetUp(self) -> None:
        self.session_manager = SessionManager(event_publisher=LoggingSessionEventPublisher())
        self.token_guard = InMemorySingleUseTokenGuard()
        self.hubs: dict[str, SessionBroadcastHub] = {}
        self.uplink_registry = IngestConnectionRegistry()
        self.server = ViewerServer(
            host="127.0.0.1",
            port=0,
            secret=SECRET,
            token_guard=self.token_guard,
            session_manager=self.session_manager,
            hubs=self.hubs,
            uplink_registry=self.uplink_registry,
        )
        await self.server.start()

    async def asyncTearDown(self) -> None:
        await self.server.stop()

    async def test_uplink_connection_is_never_added_as_a_broadcast_viewer(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="c1",
            logical_channel=1,
        )
        self.hubs[session.session_id] = SessionBroadcastHub(session.session_id, has_audio=True)
        token = mint_token(session_id=session.session_id, secret=SECRET, role="uplink")

        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader, writer, token=token)
        await asyncio.sleep(0.05)

        self.assertEqual(session.viewer_count, 0)  # never counted as a viewer
        self.assertEqual(self.hubs[session.session_id].viewer_count, 0)
        writer.close()

    async def test_binary_frames_from_the_uplink_connection_reach_the_device(self) -> None:
        session = self.session_manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="c1",
            logical_channel=1,
        )
        self.uplink_registry.register(
            session.session_id,
            writer=_FakeIngestWriter(),
            sim_card_number="014482607571",
            logical_channel=1,
        )
        token = mint_token(session_id=session.session_id, secret=SECRET, role="uplink")

        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader, writer, token=token)
        await _send_ws_binary_frame(writer, b"\xd7\xd4" * 160)
        await asyncio.sleep(0.05)

        forwarded = self.uplink_registry._connections[session.session_id]  # test-only inspection
        self.assertEqual(len(forwarded._writer.written), 1)
        writer.close()

    async def test_an_unexpected_exception_during_uplink_pump_is_caught_not_left_unhandled(
        self,
    ) -> None:
        """Live regression test (2026-09-01, physical `LSZ-C5804DG-Q-F` bench unit, real
        production intercom call): an operator's browser disconnecting its uplink socket mid-call
        surfaced as asyncio's own "Unhandled exception in client_connected_cb" — the original,
        narrower `except (ConnectionError, OSError, asyncio.IncompleteReadError)` around
        `_pump_uplink_frames` didn't cover whatever exception shape a real abrupt disconnect
        actually raised (asyncio's own default handler logs only a summary, not a full
        traceback, so the exact type could not be recovered after the fact). Proves the
        broadened `except Exception` now catches *any* exception from the pump loop — not just
        network-shaped ones — and that `_uplink_connections` bookkeeping is still cleaned up
        correctly regardless of what actually failed."""
        session = self.session_manager.create_session(
            terminal_id="T1",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="c1",
            logical_channel=1,
        )
        token = mint_token(session_id=session.session_id, secret=SECRET, role="uplink")

        async def _boom(connection, session_id) -> None:
            raise ValueError("simulated non-network failure - not IncompleteReadError/OSError")

        self.server._pump_uplink_frames = _boom  # type: ignore[method-assign]

        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader, writer, token=token)
        await asyncio.sleep(0.05)

        # No exception escaped `_handle_connection` (nothing here to assert directly on since an
        # escaped task exception wouldn't crash this test process either - the real proof is that
        # cleanup still ran exactly as it does on an ordinary disconnect):
        self.assertNotIn(session.session_id, self.server._uplink_connections)
        writer.close()

        # The server is still accepting connections afterward - a genuinely unhandled exception
        # in one connection's task must never affect any other.
        session2 = self.session_manager.create_session(
            terminal_id="T2", kind=VideoSessionKind.LIVE, correlation_id="c2", logical_channel=1
        )
        self.hubs[session2.session_id] = SessionBroadcastHub(session2.session_id)
        token2 = mint_token(session_id=session2.session_id, secret=SECRET)
        reader2, writer2 = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader2, writer2, token=token2)
        opcode, payload = await asyncio.wait_for(_read_ws_frame(reader2), timeout=2.0)
        self.assertEqual(payload[0:3], b"FLV")
        writer2.close()

    async def test_a_viewer_role_token_is_completely_unaffected(self) -> None:
        """The pre-existing downlink path, proven unchanged with a registry now configured."""
        session = self.session_manager.create_session(
            terminal_id="T1", kind=VideoSessionKind.LIVE, correlation_id="c1", logical_channel=1
        )
        self.hubs[session.session_id] = SessionBroadcastHub(session.session_id)
        token = mint_token(session_id=session.session_id, secret=SECRET, role="viewer")

        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.bound_port)
        await _ws_handshake(reader, writer, token=token)
        opcode, payload = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
        self.assertEqual(payload[0:3], b"FLV")
        await asyncio.sleep(0.05)
        self.assertEqual(session.viewer_count, 1)
        writer.close()

    async def test_uplink_role_with_no_registry_bound_is_rejected_cleanly(self) -> None:
        no_registry_server = ViewerServer(
            host="127.0.0.1",
            port=0,
            secret=SECRET,
            token_guard=InMemorySingleUseTokenGuard(),
            session_manager=self.session_manager,
            hubs=self.hubs,
        )
        await no_registry_server.start()
        try:
            session = self.session_manager.create_session(
                terminal_id="T2",
                kind=VideoSessionKind.INTERCOM,
                correlation_id="c2",
                logical_channel=1,
            )
            token = mint_token(session_id=session.session_id, secret=SECRET, role="uplink")
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", no_registry_server.bound_port
            )
            await _ws_handshake(reader, writer, token=token)
            opcode, payload = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
            self.assertEqual(opcode, 0x8)
            self.assertEqual(struct.unpack("!H", payload[0:2])[0], 4004)
            writer.close()
        finally:
            await no_registry_server.stop()


class _FakeIngestWriter:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        pass

    def is_closing(self) -> bool:
        return False


if __name__ == "__main__":
    unittest.main()
