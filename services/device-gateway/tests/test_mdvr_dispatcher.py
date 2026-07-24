"""`MdvrMessageDispatcher` tests — mirrors `test_dispatcher.py`'s conventions: known-keyword
dispatch, unknown-keyword handling (no response, no "not supported" ack - see the dispatcher's
own module docstring for why), handler-exception containment, response encoding, close-after.
"""

import unittest
from datetime import datetime, timezone

from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry
from src.vendors.lsz_mdvr.dispatcher.dispatcher import MdvrMessageDispatcher
from src.vendors.lsz_mdvr.dispatcher.handler import (
    MdvrHandlerContext,
    MdvrHandlerResult,
    MdvrMessageHandler,
)
from src.vendors.lsz_mdvr.dispatcher.registry import MdvrHandlerRegistry
from src.vendors.lsz_mdvr.protocol.message import MdvrInboundMessage
from src.vendors.lsz_mdvr.protocol.parser import parse_frame


def _make_message(keyword: str = "V109") -> MdvrInboundMessage:
    return MdvrInboundMessage(
        keyword=keyword,
        serial_no=1,
        device_serial_number="00007",
        workstation_serial_number=None,
        sent_at_raw="180903 110250",
        fields=[],
        declared_length=29,
        received_at=datetime.now(timezone.utc),
    )


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []

    async def __call__(self, connection_id: str, data: bytes) -> None:
        self.sent.append((connection_id, data))


class RecordingCloser:
    def __init__(self) -> None:
        self.closed: list[tuple[str, str]] = []

    async def __call__(self, connection_id: str, reason: str) -> None:
        self.closed.append((connection_id, reason))


class _StaticHandler(MdvrMessageHandler):
    def __init__(self, result: MdvrHandlerResult) -> None:
        self._result = result

    async def handle(self, message, context) -> MdvrHandlerResult:
        return self._result


class _RaisingHandler(MdvrMessageHandler):
    async def handle(self, message, context) -> MdvrHandlerResult:
        raise RuntimeError("boom")


def _make_dispatcher(registry: MdvrHandlerRegistry, sender: RecordingSender, closer: RecordingCloser):
    async def noop_close(connection_id: str, reason: str) -> None:
        return None

    device_sessions = DeviceSessionManager(
        registry=DeviceSessionRegistry(), close_connection=noop_close
    )
    return MdvrMessageDispatcher(
        registry=registry,
        device_sessions=device_sessions,
        send=sender,
        close_connection=closer,
    )


class MdvrMessageDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_keyword_with_response_sends_a_valid_frame(self) -> None:
        registry = MdvrHandlerRegistry()
        registry.register(
            "V109",
            _StaticHandler(MdvrHandlerResult(response_keyword="C501", response_fields=[])),
        )
        sender = RecordingSender()
        closer = RecordingCloser()
        dispatcher = _make_dispatcher(registry, sender, closer)

        await dispatcher.dispatch("conn-1", _make_message())

        self.assertEqual(len(sender.sent), 1)
        connection_id, frame = sender.sent[0]
        self.assertEqual(connection_id, "conn-1")
        message = parse_frame(frame[:-1], received_at=datetime.now(timezone.utc))
        self.assertEqual(message.keyword, "C501")
        self.assertEqual(message.device_serial_number, "00007")

    async def test_unknown_keyword_sends_no_response(self) -> None:
        registry = MdvrHandlerRegistry()
        sender = RecordingSender()
        closer = RecordingCloser()
        dispatcher = _make_dispatcher(registry, sender, closer)

        await dispatcher.dispatch("conn-1", _make_message(keyword="V999"))

        self.assertEqual(sender.sent, [])
        self.assertEqual(closer.closed, [])

    async def test_handler_exception_is_contained_not_propagated(self) -> None:
        registry = MdvrHandlerRegistry()
        registry.register("V109", _RaisingHandler())
        sender = RecordingSender()
        closer = RecordingCloser()
        dispatcher = _make_dispatcher(registry, sender, closer)

        await dispatcher.dispatch("conn-1", _make_message())  # must not raise

        self.assertEqual(sender.sent, [])

    async def test_close_connection_after_is_honored(self) -> None:
        registry = MdvrHandlerRegistry()
        registry.register(
            "V101",
            _StaticHandler(
                MdvrHandlerResult(
                    response_keyword="C100",
                    response_fields=["V101", "180903 094112", "0", "0", "2"],
                    close_connection_after=True,
                    close_reason="registration_rejected:unknown_device",
                )
            ),
        )
        sender = RecordingSender()
        closer = RecordingCloser()
        dispatcher = _make_dispatcher(registry, sender, closer)

        await dispatcher.dispatch("conn-1", _make_message(keyword="V101"))

        self.assertEqual(len(sender.sent), 1)
        self.assertEqual(closer.closed, [("conn-1", "registration_rejected:unknown_device")])


if __name__ == "__main__":
    unittest.main()
