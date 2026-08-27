"""`MdvrHeartbeatHandler` (`V109` -> `C501`) tests."""

import unittest
from datetime import datetime, timezone

from src.session.device_session import DeviceConnectivityState
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.vendors.lsz.dispatcher.handler import MdvrHandlerContext
from src.vendors.lsz.handlers.heartbeat_handler import MdvrHeartbeatHandler
from src.vendors.lsz.protocol.message import MdvrInboundMessage


def _make_message(*, device_serial_number: str = "00007") -> MdvrInboundMessage:
    return MdvrInboundMessage(
        keyword="V109",
        serial_no=13,
        device_serial_number=device_serial_number,
        workstation_serial_number=None,
        sent_at_raw="180903 110250",
        fields=[],
        declared_length=29,
        received_at=datetime.now(timezone.utc),
    )


class MdvrHeartbeatHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.handler = MdvrHeartbeatHandler()

        async def _close(connection_id: str, reason: str) -> None:
            pass

        self.device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=_close
        )

    async def test_acknowledges_with_c501_and_no_extra_fields(self) -> None:
        await self.device_sessions.create(connection_id="conn-1", terminal_id="00007")
        context = MdvrHandlerContext(
            connection_id="conn-1", device_sessions=self.device_sessions
        )
        result = await self.handler.handle(_make_message(), context)
        self.assertEqual(result.response_keyword, "C501")
        self.assertEqual(result.response_fields, [])
        self.assertFalse(result.close_connection_after)

    async def test_promotes_authenticated_session_to_online(self) -> None:
        await self.device_sessions.create(connection_id="conn-1", terminal_id="00007")
        session = await self.device_sessions.resolve("00007")
        assert session is not None
        self.assertEqual(session.state, DeviceConnectivityState.AUTHENTICATED)

        context = MdvrHandlerContext(
            connection_id="conn-1", device_sessions=self.device_sessions
        )
        await self.handler.handle(_make_message(), context)

        self.assertEqual(session.state, DeviceConnectivityState.ONLINE)

    async def test_heartbeat_for_unknown_device_is_a_safe_no_op(self) -> None:
        context = MdvrHandlerContext(
            connection_id="conn-1", device_sessions=self.device_sessions
        )
        result = await self.handler.handle(
            _make_message(device_serial_number="never-registered"), context
        )
        # Still acknowledges - the vendor protocol names no "unregistered" rejection for a
        # heartbeat the way it does for registration itself.
        self.assertEqual(result.response_keyword, "C501")


if __name__ == "__main__":
    unittest.main()
