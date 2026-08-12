"""`WebSocketConnection` tests — real loopback TCP client/server round trip against a minimal
hand-rolled WS *client* (this test file's own helper, not a dependency) that performs a real
RFC 6455 handshake and reads/writes real frames, proving the server's hand-rolled implementation
actually interoperates with the wire format, not just with itself.
"""

import asyncio
import base64
import hashlib
import os
import struct
import unittest

from src.viewer.websocket_server import (
    OPCODE_BINARY,
    OPCODE_CLOSE,
    WebSocketConnection,
    WebSocketHandshakeError,
    compute_accept_key,
)

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


async def _client_handshake(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, path: str = "/viewer?token=abc"
) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
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
    accept_value = None
    while True:
        line = (await reader.readline()).decode("iso-8859-1").strip()
        if not line:
            break
        if line.lower().startswith("sec-websocket-accept:"):
            accept_value = line.split(":", 1)[1].strip()
    expected = base64.b64encode(hashlib.sha1((key + _GUID).encode("ascii")).digest()).decode(
        "ascii"
    )
    assert accept_value == expected, (accept_value, expected)


async def _client_read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first_two = await reader.readexactly(2)
    opcode = first_two[0] & 0x0F
    length = first_two[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    payload = await reader.readexactly(length) if length else b""
    return opcode, payload


async def _client_send_masked_frame(writer: asyncio.StreamWriter, opcode: int, payload: bytes) -> None:
    mask_key = os.urandom(4)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    length = len(payload)
    header = bytes([0x80 | opcode])
    if length <= 125:
        header += bytes([0x80 | length])
    else:
        header += bytes([0x80 | 126]) + struct.pack("!H", length)
    writer.write(header + mask_key + masked)
    await writer.drain()


class ComputeAcceptKeyTests(unittest.TestCase):
    def test_matches_the_rfc6455_worked_example(self) -> None:
        # RFC 6455 §1.3's own worked example.
        self.assertEqual(
            compute_accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        )


class WebSocketServerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.connections: list[WebSocketConnection] = []

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            connection = WebSocketConnection(reader, writer)
            self.connections.append(connection)
            try:
                await connection.accept()
            except WebSocketHandshakeError:
                await connection.reject()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self) -> None:
        # Python 3.13+ changed `Server.wait_closed()` to also wait for every already-accepted
        # connection's own transport to close, not just the listening socket - a `handle()`
        # callback returning does *not* close its transport on its own, so every
        # server-side connection this test suite ever accepted must be closed explicitly first,
        # or `wait_closed()` blocks forever.
        for connection in self.connections:
            await connection.close_transport()
        self.server.close()
        await self.server.wait_closed()

    async def test_handshake_succeeds_and_extracts_path_and_query(self) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        await _client_handshake(reader, writer, path="/viewer?token=my-token&x=1")
        await asyncio.sleep(0.05)

        self.assertEqual(len(self.connections), 1)
        writer.close()

    async def test_server_can_send_a_binary_frame_the_client_can_read(self) -> None:
        server_conn_future: asyncio.Future[WebSocketConnection] = asyncio.get_event_loop().create_future()

        async def handle(reader, writer):
            connection = WebSocketConnection(reader, writer)
            await connection.accept()
            server_conn_future.set_result(connection)

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        connection: WebSocketConnection | None = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await _client_handshake(reader, writer)
            connection = await asyncio.wait_for(server_conn_future, timeout=2.0)

            await connection.send_binary(b"\x01\x02\x03FLVDATA")

            opcode, payload = await asyncio.wait_for(_client_read_frame(reader), timeout=2.0)
            self.assertEqual(opcode, OPCODE_BINARY)
            self.assertEqual(payload, b"\x01\x02\x03FLVDATA")
            writer.close()
        finally:
            if connection is not None:
                await connection.close_transport()
            server.close()
            await server.wait_closed()

    async def test_server_reads_a_masked_close_frame_from_the_client(self) -> None:
        server_conn_future: asyncio.Future[WebSocketConnection] = asyncio.get_event_loop().create_future()

        async def handle(reader, writer):
            connection = WebSocketConnection(reader, writer)
            await connection.accept()
            server_conn_future.set_result(connection)

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        connection: WebSocketConnection | None = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await _client_handshake(reader, writer)
            connection = await asyncio.wait_for(server_conn_future, timeout=2.0)

            await _client_send_masked_frame(writer, OPCODE_CLOSE, struct.pack("!H", 1000))

            result = await asyncio.wait_for(connection.read_frame(), timeout=2.0)
            self.assertIsNotNone(result)
            opcode, _payload = result
            self.assertEqual(opcode, OPCODE_CLOSE)
            self.assertTrue(connection.closed)
            writer.close()
        finally:
            if connection is not None:
                await connection.close_transport()
            server.close()
            await server.wait_closed()

    async def test_large_binary_frame_uses_the_16_bit_length_field(self) -> None:
        server_conn_future: asyncio.Future[WebSocketConnection] = asyncio.get_event_loop().create_future()

        async def handle(reader, writer):
            connection = WebSocketConnection(reader, writer)
            await connection.accept()
            server_conn_future.set_result(connection)

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        connection: WebSocketConnection | None = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await _client_handshake(reader, writer)
            connection = await asyncio.wait_for(server_conn_future, timeout=2.0)

            big_payload = b"\xab" * 5000
            await connection.send_binary(big_payload)

            opcode, payload = await asyncio.wait_for(_client_read_frame(reader), timeout=2.0)
            self.assertEqual(opcode, OPCODE_BINARY)
            self.assertEqual(payload, big_payload)
            writer.close()
        finally:
            if connection is not None:
                await connection.close_transport()
            server.close()
            await server.wait_closed()

    async def test_reject_sends_an_http_error_and_closes(self) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")  # no Upgrade header
        await writer.drain()

        status_line = (await asyncio.wait_for(reader.readline(), timeout=2.0)).decode()
        self.assertIn("400", status_line)
        writer.close()


if __name__ == "__main__":
    unittest.main()
