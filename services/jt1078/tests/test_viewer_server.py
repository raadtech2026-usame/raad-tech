"""`ViewerServer` integration tests — D5-critical: real loopback TCP/WS handshake, proving a
viewer with no valid token can never reach `hub.add_viewer` (no FLV byte, ever), and that a valid
token is honored exactly once.
"""

import asyncio
import struct
import unittest

from src.events.publisher_port import LoggingSessionEventPublisher
from src.session.session_manager import SessionManager
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

        writer.close()
        await asyncio.sleep(0.1)
        self.assertEqual(session.viewer_count, 0)


if __name__ == "__main__":
    unittest.main()
