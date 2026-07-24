"""`MdvrRegistrationHandler` (`V101` -> `C100`) tests — mirrors `test_registration_authentication_
handlers.py`'s conventions: a real `DeviceSessionManager` (in-memory registry, no-op close) plus a
fully scriptable fake provisioning port."""

import asyncio
import unittest
from datetime import datetime, timezone

from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.vendors.lsz.dispatcher.handler import MdvrHandlerContext
from src.vendors.lsz.handlers.provisioning_port import (
    MdvrDeviceProvisioningPort,
    MdvrRegistrationAuthorization,
    MdvrRegistrationResult,
)
from src.vendors.lsz.handlers.registration_handler import MdvrRegistrationHandler
from src.vendors.lsz.protocol.message import MdvrInboundMessage


def _make_message(
    *, device_serial_number: str = "00007", sent_at_raw: str = "180903 094112"
) -> MdvrInboundMessage:
    return MdvrInboundMessage(
        keyword="V101",
        serial_no=20,
        device_serial_number=device_serial_number,
        workstation_serial_number=None,
        sent_at_raw=sent_at_raw,
        fields=[],
        declared_length=227,
        received_at=datetime.now(timezone.utc),
    )


class FakeMdvrProvisioningPort(MdvrDeviceProvisioningPort):
    def __init__(self) -> None:
        self.decisions: dict[str, MdvrRegistrationAuthorization] = {}
        self.calls: list[str] = []

    async def authorize_registration(
        self, *, device_serial_number: str
    ) -> MdvrRegistrationAuthorization:
        self.calls.append(device_serial_number)
        return self.decisions.get(
            device_serial_number,
            MdvrRegistrationAuthorization(result=MdvrRegistrationResult.UNKNOWN_DEVICE),
        )


class MdvrRegistrationHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.provisioning = FakeMdvrProvisioningPort()
        self.handler = MdvrRegistrationHandler(self.provisioning)
        self.closed_connections: list[str] = []

        async def _close(connection_id: str, reason: str) -> None:
            self.closed_connections.append(connection_id)

        self.device_sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=_close
        )

    async def test_successful_registration_binds_session_and_acks_success(self) -> None:
        self.provisioning.decisions["00007"] = MdvrRegistrationAuthorization(
            result=MdvrRegistrationResult.SUCCESS,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        context = MdvrHandlerContext(
            connection_id="conn-1", device_sessions=self.device_sessions
        )
        result = await self.handler.handle(_make_message(), context)

        self.assertEqual(result.response_keyword, "C100")
        self.assertEqual(
            result.response_fields, ["V101", "180903 094112", "0", "1", ""]
        )
        self.assertFalse(result.close_connection_after)

        session = self.device_sessions.resolve("00007")
        self.assertIsNotNone(session)
        self.assertEqual(session.device_id, "device-1")
        self.assertEqual(session.vehicle_id, "vehicle-1")
        self.assertEqual(session.organization_id, "org-1")

    async def test_unknown_device_is_rejected_and_closes_connection(self) -> None:
        context = MdvrHandlerContext(
            connection_id="conn-1", device_sessions=self.device_sessions
        )
        result = await self.handler.handle(_make_message(), context)

        self.assertEqual(result.response_keyword, "C100")
        self.assertEqual(
            result.response_fields, ["V101", "180903 094112", "0", "0", "2"]
        )
        self.assertTrue(result.close_connection_after)
        self.assertIsNone(self.device_sessions.resolve("00007"))

    async def test_provisioning_port_is_asked_with_the_exact_serial_number(self) -> None:
        context = MdvrHandlerContext(
            connection_id="conn-1", device_sessions=self.device_sessions
        )
        await self.handler.handle(_make_message(device_serial_number="XYZ-42"), context)
        self.assertEqual(self.provisioning.calls, ["XYZ-42"])


if __name__ == "__main__":
    unittest.main()
