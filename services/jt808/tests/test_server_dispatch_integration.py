"""Integration verification (Phase 9.4): TCP -> Transport (Phase 9.1) -> Codec (Phase 9.3) ->
Dispatcher (Phase 9.4), against the real `Jt808Server`, using real loopback TCP clients sending
genuinely hand-framed JT/T 808-2013 packets. Confirms malformed packets never reach the
dispatcher, every registered placeholder handler is independently reachable, the unknown
handler responds over the wire, and graceful shutdown / no resource leaks hold with the
dispatcher wired in.
"""

import asyncio
import unittest
from datetime import datetime, timezone

from src.config import ServerConfig
from src.dispatcher import message_ids
from src.dispatcher.handler import HandlerResult
from src.protocol.checksum import compute_checksum
from src.protocol.escaping import escape
from src.protocol.header import encode_bcd_phone
from src.protocol.parser import PacketParser
from src.server import Jt808Server


def build_wire_frame(
    message_id: int, terminal_phone: str, serial_no: int, body: bytes = b""
) -> bytes:
    body_attrs = len(body) & 0x03FF
    header = (
        message_id.to_bytes(2, "big")
        + body_attrs.to_bytes(2, "big")
        + encode_bcd_phone(terminal_phone)
        + serial_no.to_bytes(2, "big")
    )
    payload = header + body
    checksum = compute_checksum(payload)
    return bytes([0x7E]) + escape(payload + bytes([checksum])) + bytes([0x7E])


class ServerDispatchIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = ServerConfig(host="127.0.0.1", port=0)
        self.server = Jt808Server(self.config)
        await self.server.start()
        self.port = self.server.bound_port
        self._client_writers: list[asyncio.StreamWriter] = []

    async def asyncTearDown(self) -> None:
        for writer in self._client_writers:
            if not writer.is_closing():
                writer.close()
        await self.server.stop()

    async def _open_client(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self._client_writers.append(writer)
        return reader, writer

    async def test_each_registered_message_id_reaches_its_own_handler(self) -> None:
        """Sends one frame per registered message_id over a real socket and confirms each
        correct handler receives it (matching the task's explicit requirement: "Confirm the
        correct handler receives each packet.").

        Spies via the dispatcher's `on_dispatched` hook, which fires once per successfully
        dispatched *known* message, carrying the message that was routed - a message_id
        appearing here only if its own frame was sent confirms message-ID-based routing reached
        the right registry entry, not just "some handler ran".

        **Phase 9.5 note:** `REGISTRATION` and `AUTHENTICATION` are now real handlers, not
        placeholders. Under the default fail-closed `NullDeviceProvisioningPort` (no port wired
        in this test), both a malformed/empty-body registration and an unverifiable auth code
        end with the connection closed (JT808 Technical Design §4: "reject + audit + close") -
        *after* the response is sent and `on_dispatched` fires (registration only dispatches at
        all if its body parses, so a well-formed fixed-length body is sent here). Each is sent
        on its own throwaway connection so its close doesn't cut off the other message IDs
        sharing the main connection."""
        dispatched: list[int] = []
        self.server.dispatcher._on_dispatched = lambda message: dispatched.append(
            message.message_id
        )

        _, writer = await self._open_client()
        for msg_id in [
            message_ids.TERMINAL_GENERAL_RESPONSE,
            message_ids.HEARTBEAT,
            message_ids.LOGOUT,
            message_ids.LOCATION_REPORT,
            message_ids.BULK_LOCATION_REPORT,
            message_ids.MULTIMEDIA_EVENT_UPLOAD,
        ]:
            frame = build_wire_frame(msg_id, "013800138000", 1)
            writer.write(frame)
            await writer.drain()

        # Well-formed fixed-length (37-byte) registration body so it parses and dispatches
        # (province_id, city_county_id, manufacturer_id[5], terminal_model[20],
        # manufacturer_terminal_id[7], plate_color) - content is otherwise irrelevant, since
        # the default fail-closed port rejects every registration regardless.
        registration_body = (
            (0).to_bytes(2, "big")
            + (0).to_bytes(2, "big")
            + b"\x00" * 5
            + b"\x00" * 20
            + b"\x00" * 7
            + b"\x00"
        )
        _, registration_writer = await self._open_client()
        registration_writer.write(
            build_wire_frame(
                message_ids.REGISTRATION, "013800138000", 1, body=registration_body
            )
        )
        await registration_writer.drain()

        _, auth_writer = await self._open_client()
        auth_writer.write(
            build_wire_frame(message_ids.AUTHENTICATION, "013800138000", 1)
        )
        await auth_writer.drain()

        await asyncio.sleep(0.1)

        self.assertEqual(
            sorted(dispatched),
            sorted(
                [
                    message_ids.TERMINAL_GENERAL_RESPONSE,
                    message_ids.HEARTBEAT,
                    message_ids.LOGOUT,
                    message_ids.REGISTRATION,
                    message_ids.AUTHENTICATION,
                    message_ids.LOCATION_REPORT,
                    message_ids.BULK_LOCATION_REPORT,
                    message_ids.MULTIMEDIA_EVENT_UPLOAD,
                ]
            ),
        )

    async def test_unknown_message_id_gets_a_real_wire_response(self) -> None:
        reader, writer = await self._open_client()
        frame = build_wire_frame(0x9999, "013800138000", 5)
        writer.write(frame)
        await writer.drain()

        data = await asyncio.wait_for(reader.read(64), timeout=2.0)
        self.assertTrue(data.startswith(b"\x7e") and data.endswith(b"\x7e"))

        response = PacketParser().parse(
            data[1:-1], received_at=datetime.now(timezone.utc)
        )
        self.assertEqual(response.message_id, 0x8001)
        self.assertEqual(response.body[2:4], (0x9999).to_bytes(2, "big"))

    async def test_known_placeholder_handler_sends_no_wire_response(self) -> None:
        reader, writer = await self._open_client()
        frame = build_wire_frame(message_ids.HEARTBEAT, "013800138000", 1)
        writer.write(frame)
        await writer.drain()

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.read(64), timeout=0.3)

    async def test_malformed_frame_never_reaches_dispatcher(self) -> None:
        dispatched = []
        self.server.dispatcher._on_dispatched = lambda message: dispatched.append(
            message
        )
        unknown_calls = []
        self.server.dispatcher._on_unknown_message = (
            lambda message: unknown_calls.append(message)
        )

        _, writer = await self._open_client()
        good_frame = bytearray(
            build_wire_frame(message_ids.HEARTBEAT, "013800138000", 1)
        )
        good_frame[
            -2
        ] ^= 0xFF  # corrupt the checksum byte (just before the trailing 0x7e)
        writer.write(bytes(good_frame))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(dispatched, [])
        self.assertEqual(unknown_calls, [])
        self.assertEqual(self.server.manager.connection_count, 1)  # connection survives

    async def test_graceful_shutdown_with_dispatcher_wired(self) -> None:
        for _ in range(3):
            await self._open_client()
        await asyncio.sleep(0.02)
        self.assertEqual(self.server.manager.connection_count, 3)

        await self.server.stop()
        self.assertEqual(self.server.manager.connection_count, 0)

        await self.server.start()  # so asyncTearDown's own stop() is a harmless no-op

    async def test_no_leaked_tasks_after_dispatch_cycle(self) -> None:
        before = {t for t in asyncio.all_tasks() if not t.done()}

        _, writer = await self._open_client()
        writer.write(
            build_wire_frame(0x9999, "013800138000", 1)
        )  # triggers a real response
        await writer.drain()
        await asyncio.sleep(0.1)
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.1)

        after = {t for t in asyncio.all_tasks() if not t.done()}
        leaked = after - before
        leaked = {
            t
            for t in leaked
            if "_sweep_loop" not in repr(t) and "accept_coro" not in repr(t)
        }
        self.assertEqual(leaked, set(), f"leaked tasks: {leaked}")


if __name__ == "__main__":
    unittest.main()
