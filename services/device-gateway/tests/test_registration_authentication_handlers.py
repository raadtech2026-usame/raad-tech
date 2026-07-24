"""`TerminalRegistrationHandler` (`0x0100`) and `TerminalAuthenticationHandler` (`0x0102`)
(Phase 9.5; JT808 Technical Design §4/§8, JT/T 808-2013 §8.5/§8.6/§8.8). Exercises both
handlers directly against a fake `DeviceProvisioningPort` and a real `DeviceSessionManager`
(in-memory registry, no-op close), matching the task's explicit verification list: successful
registration, registration rejection, successful authentication, authentication failure,
invalid authentication code, duplicate authentication, reconnect after authentication, session
binding, malformed packets, unknown terminal, repeated authentication attempts, concurrent
authentication.
"""

import asyncio
import unittest
from datetime import datetime, timezone

from src.dispatcher.general_response import RESULT_FAILURE, RESULT_SUCCESS
from src.dispatcher.handler import HandlerContext
from src.handlers.authentication_handler import TerminalAuthenticationHandler
from src.handlers.provisioning_port import (
    AuthenticationResult,
    DeviceProvisioningPort,
    RegistrationAuthorization,
    RegistrationResult,
)
from src.handlers.registration_handler import TerminalRegistrationHandler
from src.handlers.registration_response import REGISTRATION_RESPONSE_MESSAGE_ID
from src.protocol.exceptions import MalformedFrameError
from src.protocol.message import InboundMessage
from src.session.device_session import DeviceConnectivityState
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry


def _valid_registration_body(vehicle_identifier: bytes = b"PLATE01") -> bytes:
    return (
        (11).to_bytes(2, "big")
        + (100).to_bytes(2, "big")
        + b"MFR01"
        + b"MODEL-X".ljust(20, b"\x00")
        + b"TERM001"
        + bytes([2])
        + vehicle_identifier
    )


def _make_message(
    message_id: int,
    *,
    terminal_id: str = "013800138000",
    serial_no: int = 1,
    body: bytes = b"",
) -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        terminal_id=terminal_id,
        serial_no=serial_no,
        body=body,
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


class FakeProvisioningPort(DeviceProvisioningPort):
    """Fully scriptable double: registration/auth decisions keyed by terminal_phone, plus call
    logs so tests can assert what the handler actually asked the port for."""

    def __init__(self) -> None:
        self.registration_decisions: dict[str, RegistrationAuthorization] = {}
        self.valid_auth_codes: dict[str, str] = {}
        self.registration_calls: list[str] = []
        self.auth_calls: list[tuple[str, str]] = []

    async def authorize_registration(self, *, terminal_phone, request):
        self.registration_calls.append(terminal_phone)
        return self.registration_decisions.get(
            terminal_phone,
            RegistrationAuthorization(result=RegistrationResult.TERMINAL_NOT_FOUND),
        )

    async def verify_auth_code(self, *, terminal_phone, auth_code):
        self.auth_calls.append((terminal_phone, auth_code))
        expected = self.valid_auth_codes.get(terminal_phone)
        if expected is not None and auth_code == expected:
            return AuthenticationResult(
                is_valid=True,
                device_id=f"device-{terminal_phone}",
                vehicle_id=f"vehicle-{terminal_phone}",
                organization_id="org-1",
            )
        return AuthenticationResult(is_valid=False)


def _make_context(
    connection_id: str = "conn-1", *, device_sessions=None
) -> HandlerContext:
    if device_sessions is None:

        async def noop_close(cid, reason):
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )
    return HandlerContext(connection_id=connection_id, device_sessions=device_sessions)


class RegistrationHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_registration_returns_success_response_no_close(
        self,
    ) -> None:
        port = FakeProvisioningPort()
        port.registration_decisions["013800138000"] = RegistrationAuthorization(
            result=RegistrationResult.SUCCESS, auth_code="AUTHCODE1"
        )
        handler = TerminalRegistrationHandler(port)
        message = _make_message(0x0100, serial_no=5, body=_valid_registration_body())

        result = await handler.handle(message, _make_context())

        self.assertEqual(result.response_message_id, REGISTRATION_RESPONSE_MESSAGE_ID)
        self.assertEqual(result.response_body[0:2], (5).to_bytes(2, "big"))
        self.assertEqual(result.response_body[2], 0)
        self.assertEqual(result.response_body[3:], b"AUTHCODE1")
        self.assertFalse(result.close_connection_after)

    async def test_registration_rejection_closes_connection_after_response(
        self,
    ) -> None:
        port = FakeProvisioningPort()
        port.registration_decisions["013800138000"] = RegistrationAuthorization(
            result=RegistrationResult.TERMINAL_ALREADY_REGISTERED
        )
        handler = TerminalRegistrationHandler(port)
        message = _make_message(0x0100, body=_valid_registration_body())

        result = await handler.handle(message, _make_context())

        self.assertEqual(result.response_message_id, REGISTRATION_RESPONSE_MESSAGE_ID)
        self.assertEqual(result.response_body[2], 3)  # terminal_already_registered
        self.assertTrue(result.close_connection_after)
        self.assertEqual(
            result.close_reason, "registration_rejected:terminal_already_registered"
        )

    async def test_unknown_terminal_registration_rejected(self) -> None:
        port = (
            FakeProvisioningPort()
        )  # no decision registered -> falls back to TERMINAL_NOT_FOUND
        handler = TerminalRegistrationHandler(port)
        message = _make_message(0x0100, body=_valid_registration_body())

        result = await handler.handle(message, _make_context())

        self.assertEqual(result.response_body[2], 4)  # terminal_not_found
        self.assertTrue(result.close_connection_after)

    async def test_malformed_registration_body_raises_rather_than_responds(
        self,
    ) -> None:
        port = FakeProvisioningPort()
        handler = TerminalRegistrationHandler(port)
        message = _make_message(
            0x0100, body=b"\x00" * 10
        )  # short of 37-byte fixed portion

        with self.assertRaises(MalformedFrameError):
            await handler.handle(message, _make_context())

        self.assertEqual(port.registration_calls, [])  # never reached the port

    async def test_registration_does_not_create_a_device_session(self) -> None:
        port = FakeProvisioningPort()
        port.registration_decisions["013800138000"] = RegistrationAuthorization(
            result=RegistrationResult.SUCCESS, auth_code="X"
        )
        handler = TerminalRegistrationHandler(port)
        context = _make_context()
        message = _make_message(0x0100, body=_valid_registration_body())

        await handler.handle(message, context)

        self.assertIsNone(context.device_sessions.resolve("013800138000"))


class AuthenticationHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_authentication_binds_session_and_responds_success(
        self,
    ) -> None:
        port = FakeProvisioningPort()
        port.valid_auth_codes["013800138000"] = "SECRET"
        handler = TerminalAuthenticationHandler(port)
        context = _make_context("conn-1")
        message = _make_message(0x0102, serial_no=7, body="SECRET".encode("gbk"))

        result = await handler.handle(message, context)

        self.assertEqual(result.response_body[0:2], (7).to_bytes(2, "big"))
        self.assertEqual(result.response_body[2:4], (0x0102).to_bytes(2, "big"))
        self.assertEqual(result.response_body[4], RESULT_SUCCESS)
        self.assertFalse(result.close_connection_after)

        session = context.device_sessions.resolve("013800138000")
        self.assertIsNotNone(session)
        self.assertEqual(session.connection_id, "conn-1")
        self.assertEqual(session.device_id, "device-013800138000")
        self.assertEqual(session.vehicle_id, "vehicle-013800138000")
        self.assertEqual(session.organization_id, "org-1")
        self.assertEqual(session.state, DeviceConnectivityState.AUTHENTICATED)

    async def test_authentication_failure_closes_connection_and_binds_no_session(
        self,
    ) -> None:
        port = FakeProvisioningPort()
        port.valid_auth_codes["013800138000"] = "SECRET"
        handler = TerminalAuthenticationHandler(port)
        context = _make_context("conn-1")
        message = _make_message(0x0102, body="WRONG".encode("gbk"))

        result = await handler.handle(message, context)

        self.assertEqual(result.response_body[4], RESULT_FAILURE)
        self.assertTrue(result.close_connection_after)
        self.assertEqual(result.close_reason, "authentication_failed")
        self.assertIsNone(context.device_sessions.resolve("013800138000"))

    async def test_invalid_authentication_code_for_unregistered_terminal_fails(
        self,
    ) -> None:
        port = FakeProvisioningPort()  # no valid codes registered at all
        handler = TerminalAuthenticationHandler(port)
        message = _make_message(0x0102, body="ANYTHING".encode("gbk"))

        result = await handler.handle(message, _make_context())

        self.assertEqual(result.response_body[4], RESULT_FAILURE)
        self.assertTrue(result.close_connection_after)

    async def test_repeated_authentication_on_same_connection_reuses_session_no_supersede(
        self,
    ) -> None:
        port = FakeProvisioningPort()
        port.valid_auth_codes["013800138000"] = "SECRET"
        handler = TerminalAuthenticationHandler(port)

        superseded = []

        async def noop_close(cid, reason):
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(),
            close_connection=noop_close,
            on_session_superseded=lambda old, new: superseded.append((old, new)),
        )
        context = HandlerContext(
            connection_id="conn-1", device_sessions=device_sessions
        )

        for serial in (1, 2, 3):
            result = await handler.handle(
                _make_message(0x0102, serial_no=serial, body="SECRET".encode("gbk")),
                context,
            )
            self.assertFalse(result.close_connection_after)

        self.assertEqual(port.auth_calls, [("013800138000", "SECRET")] * 3)
        self.assertEqual(
            superseded, []
        )  # same connection re-authenticating is not a supersede
        session = device_sessions.resolve("013800138000")
        self.assertEqual(session.connection_id, "conn-1")

    async def test_duplicate_authentication_from_a_different_connection_supersedes(
        self,
    ) -> None:
        port = FakeProvisioningPort()
        port.valid_auth_codes["013800138000"] = "SECRET"
        handler = TerminalAuthenticationHandler(port)

        closed: list[str] = []

        async def recording_close(cid, reason):
            closed.append(cid)

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=recording_close
        )

        await handler.handle(
            _make_message(0x0102, body="SECRET".encode("gbk")),
            HandlerContext(connection_id="conn-A", device_sessions=device_sessions),
        )
        await handler.handle(
            _make_message(0x0102, body="SECRET".encode("gbk")),
            HandlerContext(connection_id="conn-B", device_sessions=device_sessions),
        )

        self.assertEqual(closed, ["conn-A"])  # older connection superseded and closed
        session = device_sessions.resolve("013800138000")
        self.assertEqual(session.connection_id, "conn-B")

    async def test_reconnect_after_authentication_creates_fresh_session_on_new_connection(
        self,
    ) -> None:
        port = FakeProvisioningPort()
        port.valid_auth_codes["013800138000"] = "SECRET"
        handler = TerminalAuthenticationHandler(port)

        async def noop_close(cid, reason):
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )

        await handler.handle(
            _make_message(0x0102, body="SECRET".encode("gbk")),
            HandlerContext(connection_id="conn-1", device_sessions=device_sessions),
        )
        await device_sessions.close("013800138000", reason="connection_closed")
        self.assertIsNone(device_sessions.resolve("013800138000"))

        await handler.handle(
            _make_message(0x0102, body="SECRET".encode("gbk")),
            HandlerContext(connection_id="conn-2", device_sessions=device_sessions),
        )
        session = device_sessions.resolve("013800138000")
        self.assertIsNotNone(session)
        self.assertEqual(session.connection_id, "conn-2")

    async def test_concurrent_authentication_across_distinct_terminals_all_bind(
        self,
    ) -> None:
        port = FakeProvisioningPort()
        terminal_ids = [f"01380013{i:04d}" for i in range(10)]
        for terminal_id in terminal_ids:
            port.valid_auth_codes[terminal_id] = "SECRET"
        handler = TerminalAuthenticationHandler(port)

        async def noop_close(cid, reason):
            return None

        device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )

        await asyncio.gather(
            *[
                handler.handle(
                    _make_message(
                        0x0102, terminal_id=terminal_id, body="SECRET".encode("gbk")
                    ),
                    HandlerContext(
                        connection_id=f"conn-{terminal_id}",
                        device_sessions=device_sessions,
                    ),
                )
                for terminal_id in terminal_ids
            ]
        )

        for terminal_id in terminal_ids:
            session = device_sessions.resolve(terminal_id)
            self.assertIsNotNone(session)
            self.assertEqual(session.connection_id, f"conn-{terminal_id}")


if __name__ == "__main__":
    unittest.main()
