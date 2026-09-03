"""Minimal RFC 6455 WebSocket server — hand-rolled against the public RFC text (stable,
unambiguous, not JT/T-1078-specific), stdlib `asyncio`/`hashlib`/`base64`/`struct` only.
Deliberately narrow: this relay only ever *sends* binary (FLV) frames to a viewer and needs to
*detect* the viewer's own close/ping/pong — it never needs arbitrary bidirectional messaging,
fragmentation, or extensions, so none of that RFC surface is implemented.

**Handshake** (RFC 6455 §4.2.2): reads the client's HTTP Upgrade request line + headers,
computes `Sec-WebSocket-Accept = base64(sha1(Sec-WebSocket-Key + GUID))` (the RFC's own fixed
GUID, `258EAFA5-E914-47DA-95CA-C5AB0DC85B11`), and writes the `101 Switching Protocols` response.

**Outbound frames are never masked** — RFC 6455 §5.1: "a server MUST NOT mask any frames that it
sends to the client." **Inbound frames from a real browser client are always masked** — §5.3:
"a client MUST mask all frames... sent to the server"; `_read_frame` unmasks with the frame's own
4-byte masking key (XOR per byte, `mask[i % 4]`) before returning the payload.

**No fragmentation, no extensions, no compression** — every frame this module sends has `FIN=1`;
every frame it reads is expected to also have `FIN=1` (a real close/ping frame is never
fragmented per RFC 6455 §5.4's own control-frame rule, and this relay never expects a data frame
*from* the viewer at all).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
from urllib.parse import urlsplit, parse_qs

_HANDSHAKE_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


class WebSocketHandshakeError(Exception):
    """The inbound request was not a valid WebSocket upgrade request."""


class WebSocketClosed(Exception):
    """Raised by `read_frame`/`send_*` once the connection is known closed."""


def compute_accept_key(sec_websocket_key: str) -> str:
    digest = hashlib.sha1((sec_websocket_key + _HANDSHAKE_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


async def _read_http_headers(reader: asyncio.StreamReader) -> tuple[str, dict[str, str]]:
    request_line = (await reader.readline()).decode("iso-8859-1").strip()
    if not request_line:
        raise WebSocketHandshakeError("Empty request line.")
    headers: dict[str, str] = {}
    while True:
        line = (await reader.readline()).decode("iso-8859-1").strip()
        if not line:
            break
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return request_line, headers


class WebSocketConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._closed = False
        #: Serializes every `write()`+`await drain()` pair on this connection (2026-09-02).
        #: Three independent tasks can write to the *same* connection concurrently:
        #: `SessionBroadcastHub._run_sender` (FLV chunks), `ViewerServer._ping_loop` (the
        #: keepalive ping added the same day), and `ViewerServer.close_session`/
        #: `SessionBroadcastHub.close_all` (the terminal close frame). `asyncio`'s own
        #: `FlowControlMixin._drain_helper` asserts `self._drain_waiter is None or ...cancelled()`
        #: — so two tasks awaiting `drain()` while the transport is *paused* (exactly what a
        #: slow/lossy viewer causes, by exceeding the high-water mark) raises `AssertionError`
        #: out of the second one. That surfaces as this hub's own `viewer_sender_task_crashed`
        #: and silently drops an otherwise-healthy viewer. Holding the lock across write+drain
        #: makes that impossible without changing frame ordering (a frame's bytes already reach
        #: the transport in one `write()` call, so no frame could ever interleave — only the
        #: concurrent `drain()` was unsafe).
        self._write_lock = asyncio.Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    async def accept(self) -> tuple[str, dict[str, list[str]]]:
        """Performs the handshake. Returns `(path, query_params)` from the request line, so the
        caller (`relay.py`'s viewer route) can extract the signed token from the query string —
        this module knows nothing about tokens or sessions itself."""
        request_line, headers = await _read_http_headers(self._reader)
        parts = request_line.split(" ")
        if len(parts) < 2:
            raise WebSocketHandshakeError(f"Malformed request line: {request_line!r}")
        target = parts[1]
        split = urlsplit(target)

        if headers.get("upgrade", "").lower() != "websocket":
            raise WebSocketHandshakeError("Missing or invalid Upgrade header.")
        sec_key = headers.get("sec-websocket-key")
        if not sec_key:
            raise WebSocketHandshakeError("Missing Sec-WebSocket-Key header.")

        accept_key = compute_accept_key(sec_key)
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n"
            "\r\n"
        )
        self._writer.write(response.encode("iso-8859-1"))
        await self._writer.drain()
        return split.path, parse_qs(split.query)

    async def reject(self, *, status: str = "400 Bad Request") -> None:
        response = f"HTTP/1.1 {status}\r\nConnection: close\r\n\r\n"
        self._writer.write(response.encode("iso-8859-1"))
        await self._writer.drain()
        self._writer.close()
        self._closed = True

    def _build_frame(self, opcode: int, payload: bytes) -> bytes:
        header = bytes([0x80 | opcode])  # FIN=1, RSV=0
        length = len(payload)
        if length <= 125:
            header += bytes([length])  # MASK bit 0 - server frames are never masked
        elif length <= 0xFFFF:
            header += bytes([126]) + struct.pack("!H", length)
        else:
            header += bytes([127]) + struct.pack("!Q", length)
        return header + payload

    async def send_binary(self, data: bytes) -> None:
        if self._closed:
            raise WebSocketClosed("Cannot send on a closed WebSocket connection.")
        frame = self._build_frame(OPCODE_BINARY, data)
        async with self._write_lock:
            self._writer.write(frame)
            await self._writer.drain()

    async def send_close(self, *, code: int = 1000, reason: bytes = b"") -> None:
        if self._closed:
            return
        payload = struct.pack("!H", code) + reason
        frame = self._build_frame(OPCODE_CLOSE, payload)
        try:
            async with self._write_lock:
                self._writer.write(frame)
                await self._writer.drain()
        finally:
            self._closed = True
            self._writer.close()

    async def send_pong(self, payload: bytes = b"") -> None:
        frame = self._build_frame(OPCODE_PONG, payload)
        async with self._write_lock:
            self._writer.write(frame)
            await self._writer.drain()

    async def send_ping(self, payload: bytes = b"") -> None:
        """RFC 6455 §5.5.2 — a server-initiated keepalive ping (2026-09-02, diagnosing the
        browser<->relay ~32s disconnect). This server previously never sent one at all: it only
        ever *replied* to a client-initiated ping (`send_pong` above). A conformant browser
        WebSocket client responds to this transparently at the protocol level (no application/JS
        involvement needed on the browser side) - `viewer/viewer_server.py`'s own read loops
        already tolerate an unexpected opcode without erroring, so no other change is needed to
        receive the resulting pong. Raises `WebSocketClosed` on an already-closed connection,
        matching `send_binary`'s own contract — the caller (`ViewerServer`'s ping loop) treats
        that, and any other send failure, as "this connection is already gone," not an error."""
        if self._closed:
            raise WebSocketClosed("Cannot send on a closed WebSocket connection.")
        frame = self._build_frame(OPCODE_PING, payload)
        async with self._write_lock:
            self._writer.write(frame)
            await self._writer.drain()

    async def read_frame(self) -> tuple[int, bytes] | None:
        """Reads one client->server frame (always masked, RFC 6455 §5.3). Returns `(opcode,
        payload)`, or `None` on a clean EOF (the viewer's own TCP connection closed)."""
        first_two = await self._reader.readexactly(2)
        if not first_two:
            return None
        opcode = first_two[0] & 0x0F
        masked = bool(first_two[1] & 0x80)
        length = first_two[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", await self._reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await self._reader.readexactly(8))[0]

        mask_key = await self._reader.readexactly(4) if masked else b""
        payload = await self._reader.readexactly(length) if length else b""
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        if opcode == OPCODE_CLOSE:
            self._closed = True
        return opcode, payload

    async def close_transport(self) -> None:
        self._closed = True
        if not self._writer.is_closing():
            self._writer.close()
