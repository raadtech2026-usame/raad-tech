"""Full-stack Phase 9.5 integration: real loopback TCP client, real `Jt808Server` (transport +
codec + dispatcher + registration/authentication handlers), a scriptable `DeviceProvisioningPort`
double standing in for the not-yet-built real provisioning implementation. Exercises the task's
own manual-verification scenario end to end: Register -> Authenticate -> Heartbeat-ready state,
plus registration response encoding, authentication response encoding over the wire, and clean
shutdown with a bound device session.
"""

import asyncio
import unittest
from datetime import datetime, timezone

from src.config import ServerConfig
from src.handlers.provisioning_port import (
    AuthenticationResult,
    DeviceProvisioningPort,
    RegistrationAuthorization,
    RegistrationResult,
)
from src.protocol.checksum import compute_checksum
from src.protocol.escaping import escape
from src.protocol.header import encode_bcd_phone
from src.protocol.parser import PacketParser
from src.protocol.strings import encode_gbk_string
from src.server import Jt808Server

TERMINAL_PHONE = "013800138000"
AUTH_CODE = "GRANTED-CODE-1"


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


def registration_body(vehicle_identifier: bytes = b"PLATE01") -> bytes:
    return (
        (11).to_bytes(2, "big")
        + (100).to_bytes(2, "big")
        + b"MFR01"
        + b"MODEL-X".ljust(20, b"\x00")
        + b"TERM001"
        + bytes([2])
        + vehicle_identifier
    )


class ScriptedProvisioningPort(DeviceProvisioningPort):
    """Grants registration/authentication for exactly the phones the test configures — the
    real seam a future device-provisioning implementation fills; this double stands in so
    Phase 9.5's protocol behavior can be verified end to end without one."""

    def __init__(self) -> None:
        self.granted_registrations: set[str] = set()
        self.granted_auth_codes: dict[str, str] = {}

    async def authorize_registration(self, *, terminal_phone, request):
        if terminal_phone in self.granted_registrations:
            return RegistrationAuthorization(
                result=RegistrationResult.SUCCESS,
                auth_code=AUTH_CODE,
                device_id="device-1",
                vehicle_id="vehicle-1",
                organization_id="org-1",
            )
        return RegistrationAuthorization(result=RegistrationResult.TERMINAL_NOT_FOUND)

    async def verify_auth_code(self, *, terminal_phone, auth_code):
        expected = self.granted_auth_codes.get(terminal_phone)
        if expected is not None and auth_code == expected:
            return AuthenticationResult(
                is_valid=True,
                device_id="device-1",
                vehicle_id="vehicle-1",
                organization_id="org-1",
            )
        return AuthenticationResult(is_valid=False)


class AuthenticationRegistrationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = ServerConfig(host="127.0.0.1", port=0)
        self.provisioning = ScriptedProvisioningPort()
        self.server = Jt808Server(self.config, device_provisioning=self.provisioning)
        await self.server.start()
        self.port = self.server.bound_port
        self._client_writers: list[asyncio.StreamWriter] = []
        self.parser = PacketParser()

    async def asyncTearDown(self) -> None:
        for writer in self._client_writers:
            if not writer.is_closing():
                writer.close()
        await self.server.stop()

    async def _open_client(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self._client_writers.append(writer)
        return reader, writer

    async def _read_frame(self, reader: asyncio.StreamReader):
        data = await asyncio.wait_for(reader.read(256), timeout=2.0)
        return self.parser.parse(data[1:-1], received_at=datetime.now(timezone.utc))

    async def test_register_then_authenticate_reaches_heartbeat_ready_state(
        self,
    ) -> None:
        self.provisioning.granted_registrations.add(TERMINAL_PHONE)
        self.provisioning.granted_auth_codes[TERMINAL_PHONE] = AUTH_CODE

        reader, writer = await self._open_client()

        writer.write(
            build_wire_frame(0x0100, TERMINAL_PHONE, 1, body=registration_body())
        )
        await writer.drain()
        registration_response = await self._read_frame(reader)
        self.assertEqual(registration_response.message_id, 0x8100)
        self.assertEqual(registration_response.body[2], 0)  # success
        granted_code = registration_response.body[3:].decode("gbk")
        self.assertEqual(granted_code, AUTH_CODE)

        writer.write(
            build_wire_frame(
                0x0102, TERMINAL_PHONE, 2, body=encode_gbk_string(granted_code)
            )
        )
        await writer.drain()
        auth_response = await self._read_frame(reader)
        self.assertEqual(auth_response.message_id, 0x8001)
        self.assertEqual(auth_response.body[4], 0)  # RESULT_SUCCESS

        # Heartbeat-ready: a bound, AUTHENTICATED DeviceSession exists and the connection is
        # still open (not torn down) - the state a real Heartbeat handler (future phase) would
        # `touch()` to promote to ONLINE.
        session = self.server.device_sessions.resolve(TERMINAL_PHONE)
        self.assertIsNotNone(session)
        self.assertEqual(session.state.value, "authenticated")
        self.assertEqual(self.server.manager.connection_count, 1)

    async def test_registration_rejection_sends_response_then_closes_socket(
        self,
    ) -> None:
        # Nothing granted -> TERMINAL_NOT_FOUND.
        reader, writer = await self._open_client()
        writer.write(
            build_wire_frame(0x0100, TERMINAL_PHONE, 1, body=registration_body())
        )
        await writer.drain()

        response = await self._read_frame(reader)
        self.assertEqual(response.message_id, 0x8100)
        self.assertEqual(response.body[2], 4)  # terminal_not_found

        # Server closes its end after the rejection - the client's next read hits EOF.
        data = await asyncio.wait_for(reader.read(1), timeout=2.0)
        self.assertEqual(data, b"")

    async def test_authentication_failure_sends_response_then_closes_socket(
        self,
    ) -> None:
        self.provisioning.granted_auth_codes[TERMINAL_PHONE] = AUTH_CODE
        reader, writer = await self._open_client()
        writer.write(
            build_wire_frame(
                0x0102, TERMINAL_PHONE, 1, body=encode_gbk_string("WRONG-CODE")
            )
        )
        await writer.drain()

        response = await self._read_frame(reader)
        self.assertEqual(response.message_id, 0x8001)
        self.assertEqual(response.body[4], 1)  # RESULT_FAILURE

        data = await asyncio.wait_for(reader.read(1), timeout=2.0)
        self.assertEqual(data, b"")

        self.assertIsNone(self.server.device_sessions.resolve(TERMINAL_PHONE))

    async def test_duplicate_authentication_supersedes_older_connection_over_the_wire(
        self,
    ) -> None:
        self.provisioning.granted_auth_codes[TERMINAL_PHONE] = AUTH_CODE

        reader_a, writer_a = await self._open_client()
        writer_a.write(
            build_wire_frame(
                0x0102, TERMINAL_PHONE, 1, body=encode_gbk_string(AUTH_CODE)
            )
        )
        await writer_a.drain()
        await self._read_frame(reader_a)  # success

        reader_b, writer_b = await self._open_client()
        writer_b.write(
            build_wire_frame(
                0x0102, TERMINAL_PHONE, 1, body=encode_gbk_string(AUTH_CODE)
            )
        )
        await writer_b.drain()
        await self._read_frame(reader_b)  # success

        # conn-A gets superseded-closed; its socket sees EOF.
        data = await asyncio.wait_for(reader_a.read(1), timeout=2.0)
        self.assertEqual(data, b"")

        session = self.server.device_sessions.resolve(TERMINAL_PHONE)
        self.assertIsNotNone(session)
        self.assertEqual(self.server.manager.connection_count, 1)

    async def test_malformed_registration_frame_never_reaches_dispatcher_and_survives(
        self,
    ) -> None:
        dispatched = []
        self.server.dispatcher._on_dispatched = lambda message: dispatched.append(
            message.message_id
        )

        _, writer = await self._open_client()
        good_frame = bytearray(
            build_wire_frame(0x0100, TERMINAL_PHONE, 1, body=registration_body())
        )
        good_frame[-2] ^= 0xFF  # corrupt checksum
        writer.write(bytes(good_frame))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(dispatched, [])
        self.assertEqual(self.server.manager.connection_count, 1)  # connection survives

    async def test_clean_shutdown_after_authentication_leaves_no_sessions_or_connections(
        self,
    ) -> None:
        self.provisioning.granted_auth_codes[TERMINAL_PHONE] = AUTH_CODE
        reader, writer = await self._open_client()
        writer.write(
            build_wire_frame(
                0x0102, TERMINAL_PHONE, 1, body=encode_gbk_string(AUTH_CODE)
            )
        )
        await writer.drain()
        await self._read_frame(reader)

        self.assertEqual(self.server.device_session_count, 1)
        await self.server.stop()

        self.assertEqual(self.server.manager.connection_count, 0)
        self.assertEqual(self.server.device_session_count, 0)

        await self.server.start()  # asyncTearDown's own stop() becomes a harmless no-op


if __name__ == "__main__":
    unittest.main()
