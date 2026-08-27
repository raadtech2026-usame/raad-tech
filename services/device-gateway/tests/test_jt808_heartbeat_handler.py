"""`HeartbeatHandler` (`0x0002` -> `0x8001`) tests — mirrors `test_mdvr_heartbeat_handler.py`
(the LSZ equivalent) exactly, adapted to JT808's general-response wire shape."""

import unittest
from datetime import datetime, timezone

from src.session.device_session import DeviceConnectivityState
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.vendors.jt808.dispatcher.handler import HandlerContext
from src.vendors.jt808.handlers.heartbeat_handler import HeartbeatHandler
from src.vendors.jt808.protocol.message import InboundMessage

TERMINAL_ID = "013800138000"


def _make_message(
    *, terminal_id: str = TERMINAL_ID, serial_no: int = 13
) -> InboundMessage:
    return InboundMessage(
        message_id=0x0002,
        terminal_id=terminal_id,
        serial_no=serial_no,
        body=b"",
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


class HeartbeatHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.handler = HeartbeatHandler()

        async def _close(connection_id: str, reason: str) -> None:
            pass

        self.device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=_close
        )

    async def test_acknowledges_with_general_response_success(self) -> None:
        await self.device_sessions.create(connection_id="conn-1", terminal_id=TERMINAL_ID)
        context = HandlerContext(connection_id="conn-1", device_sessions=self.device_sessions)

        result = await self.handler.handle(_make_message(serial_no=7), context)

        self.assertEqual(result.response_message_id, 0x8001)
        self.assertEqual(result.response_body[0:2], (7).to_bytes(2, "big"))
        self.assertEqual(result.response_body[2:4], (0x0002).to_bytes(2, "big"))
        self.assertEqual(result.response_body[4], 0)  # RESULT_SUCCESS
        self.assertFalse(result.close_connection_after)

    async def test_promotes_authenticated_session_to_online(self) -> None:
        await self.device_sessions.create(connection_id="conn-1", terminal_id=TERMINAL_ID)
        session = await self.device_sessions.resolve(TERMINAL_ID)
        assert session is not None
        self.assertEqual(session.state, DeviceConnectivityState.AUTHENTICATED)

        context = HandlerContext(connection_id="conn-1", device_sessions=self.device_sessions)
        await self.handler.handle(_make_message(), context)

        self.assertEqual(session.state, DeviceConnectivityState.ONLINE)

    async def test_heartbeat_for_unknown_terminal_is_a_safe_no_op(self) -> None:
        context = HandlerContext(connection_id="conn-1", device_sessions=self.device_sessions)
        result = await self.handler.handle(
            _make_message(terminal_id="never-registered"), context
        )
        # Still acknowledges - JT/T 808-2013's general-response table (§8.2) has no "unknown
        # device" result code for heartbeat to distinguish this case with.
        self.assertEqual(result.response_message_id, 0x8001)
        self.assertEqual(result.response_body[4], 0)  # RESULT_SUCCESS

    async def test_second_heartbeat_does_not_refire_online_promotion(self) -> None:
        await self.device_sessions.create(connection_id="conn-1", terminal_id=TERMINAL_ID)
        session = await self.device_sessions.resolve(TERMINAL_ID)
        context = HandlerContext(connection_id="conn-1", device_sessions=self.device_sessions)

        await self.handler.handle(_make_message(serial_no=1), context)
        self.assertEqual(session.state, DeviceConnectivityState.ONLINE)

        # A second heartbeat on an already-ONLINE session must not raise or regress state.
        result = await self.handler.handle(_make_message(serial_no=2), context)
        self.assertEqual(session.state, DeviceConnectivityState.ONLINE)
        self.assertEqual(result.response_body[4], 0)  # RESULT_SUCCESS


if __name__ == "__main__":
    unittest.main()
