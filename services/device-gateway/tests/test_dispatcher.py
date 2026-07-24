"""MessageDispatcher tests (Phase 9.4): known message dispatch, unknown message dispatch,
handler exception containment, concurrent dispatch, response propagation.
"""

import asyncio
import unittest
from datetime import datetime, timezone

from src.dispatcher.dispatcher import MessageDispatcher
from src.dispatcher.general_response import (
    GENERAL_RESPONSE_MESSAGE_ID,
    RESULT_NOT_SUPPORTED,
)
from src.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.dispatcher.registry import HandlerRegistry
from src.dispatcher.unknown_handler import UnknownMessageHandler
from src.protocol.message import InboundMessage
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry


def make_message(
    message_id: int, terminal_id: str = "013800138000", serial_no: int = 1
) -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        terminal_id=terminal_id,
        serial_no=serial_no,
        body=b"",
        encryption_method=0,
        received_at=datetime.now(timezone.utc),
    )


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []

    async def __call__(self, connection_id: str, data: bytes) -> None:
        self.sent.append((connection_id, data))


def make_dispatcher(**overrides):
    async def noop_close_connection(connection_id: str, reason: str) -> None:
        return None

    device_sessions = overrides.pop(
        "device_sessions",
        DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close_connection
        ),
    )
    sender = overrides.pop("sender", RecordingSender())
    registry = overrides.pop("registry", HandlerRegistry())
    unknown_handler = overrides.pop("unknown_handler", UnknownMessageHandler())
    close_connection = overrides.pop("close_connection", noop_close_connection)
    dispatcher = MessageDispatcher(
        registry=registry,
        unknown_handler=unknown_handler,
        device_sessions=device_sessions,
        send=sender,
        close_connection=close_connection,
        **overrides,
    )
    return dispatcher, registry, sender


class _RecordingHandler(MessageHandler):
    def __init__(self, result: HandlerResult | None = None) -> None:
        self.calls: list[tuple[InboundMessage, HandlerContext]] = []
        self._result = result or HandlerResult.no_response()

    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        self.calls.append((message, context))
        return self._result


class _RaisingHandler(MessageHandler):
    async def handle(self, message, context) -> HandlerResult:
        raise RuntimeError("handler bug")


class KnownMessageDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_to_registered_handler(self) -> None:
        handler = _RecordingHandler()
        registry = HandlerRegistry()
        registry.register(0x0002, handler)
        dispatcher, _, sender = make_dispatcher(registry=registry)

        message = make_message(0x0002)
        await dispatcher.dispatch("conn-1", message)

        self.assertEqual(len(handler.calls), 1)
        called_message, called_context = handler.calls[0]
        self.assertIs(called_message, message)
        self.assertEqual(called_context.connection_id, "conn-1")

    async def test_handler_context_carries_device_sessions(self) -> None:
        handler = _RecordingHandler()
        registry = HandlerRegistry()
        registry.register(0x0002, handler)

        async def noop_close(cid, reason):
            return None

        sessions = DeviceSessionManager(
            registry=DeviceSessionRegistry(), close_connection=noop_close
        )
        dispatcher, _, _ = make_dispatcher(registry=registry, device_sessions=sessions)
        await dispatcher.dispatch("conn-1", make_message(0x0002))

        _, context = handler.calls[0]
        self.assertIs(context.device_sessions, sessions)

    async def test_only_matching_message_id_dispatches_to_a_handler(self) -> None:
        heartbeat_handler = _RecordingHandler()
        location_handler = _RecordingHandler()
        registry = HandlerRegistry()
        registry.register(0x0002, heartbeat_handler)
        registry.register(0x0200, location_handler)
        dispatcher, _, _ = make_dispatcher(registry=registry)

        await dispatcher.dispatch("conn-1", make_message(0x0002))

        self.assertEqual(len(heartbeat_handler.calls), 1)
        self.assertEqual(len(location_handler.calls), 0)


class UnknownMessageDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_unmatched_message_id_routes_to_unknown_handler(self) -> None:
        dispatcher, _, sender = make_dispatcher()
        message = make_message(0x9999, serial_no=42)

        await dispatcher.dispatch("conn-1", message)

        self.assertEqual(len(sender.sent), 1)
        connection_id, frame = sender.sent[0]
        self.assertEqual(connection_id, "conn-1")
        self.assertEqual(frame[0], 0x7E)
        self.assertEqual(frame[-1], 0x7E)

    async def test_unknown_message_response_decodes_to_not_supported(self) -> None:
        from src.protocol.parser import PacketParser

        dispatcher, _, sender = make_dispatcher()
        await dispatcher.dispatch("conn-1", make_message(0x9999, serial_no=42))

        _, frame = sender.sent[0]
        response = PacketParser().parse(
            frame[1:-1], received_at=datetime.now(timezone.utc)
        )
        self.assertEqual(response.message_id, GENERAL_RESPONSE_MESSAGE_ID)
        # body: response_serial_no(2) + response_message_id(2) + result(1)
        self.assertEqual(response.body[0:2], (42).to_bytes(2, "big"))
        self.assertEqual(response.body[2:4], (0x9999).to_bytes(2, "big"))
        self.assertEqual(response.body[4], RESULT_NOT_SUPPORTED)

    async def test_known_message_id_never_reaches_unknown_handler(self) -> None:
        handler = _RecordingHandler()
        registry = HandlerRegistry()
        registry.register(0x0002, handler)
        dispatcher, _, sender = make_dispatcher(registry=registry)

        await dispatcher.dispatch("conn-1", make_message(0x0002))

        self.assertEqual(sender.sent, [])  # known handler sent nothing (no_response)


class HandlerExceptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_exception_does_not_propagate(self) -> None:
        registry = HandlerRegistry()
        registry.register(0x0002, _RaisingHandler())
        dispatcher, _, _ = make_dispatcher(registry=registry)

        # Must not raise.
        await dispatcher.dispatch("conn-1", make_message(0x0002))

    async def test_handler_exception_invokes_on_handler_error(self) -> None:
        errors = []
        registry = HandlerRegistry()
        registry.register(0x0002, _RaisingHandler())
        dispatcher, _, _ = make_dispatcher(
            registry=registry,
            on_handler_error=lambda message, exc: errors.append((message, exc)),
        )

        await dispatcher.dispatch("conn-1", make_message(0x0002))

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0][1], RuntimeError)

    async def test_handler_exception_sends_no_response(self) -> None:
        registry = HandlerRegistry()
        registry.register(0x0002, _RaisingHandler())
        dispatcher, _, sender = make_dispatcher(registry=registry)

        await dispatcher.dispatch("conn-1", make_message(0x0002))

        self.assertEqual(sender.sent, [])

    async def test_dispatcher_survives_multiple_consecutive_handler_errors(
        self,
    ) -> None:
        registry = HandlerRegistry()
        registry.register(0x0002, _RaisingHandler())
        dispatcher, _, _ = make_dispatcher(registry=registry)

        for _ in range(5):
            await dispatcher.dispatch("conn-1", make_message(0x0002))  # must not raise


class ResponsePropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_sent_to_the_originating_connection(self) -> None:
        handler = _RecordingHandler(
            result=HandlerResult(
                response_message_id=0x8001, response_body=b"\x00\x01\x00\x02\x00"
            )
        )
        registry = HandlerRegistry()
        registry.register(0x0002, handler)
        dispatcher, _, sender = make_dispatcher(registry=registry)

        await dispatcher.dispatch(
            "conn-A", make_message(0x0002, terminal_id="013800138000")
        )
        await dispatcher.dispatch(
            "conn-B", make_message(0x0002, terminal_id="013900139000")
        )

        self.assertEqual(len(sender.sent), 2)
        self.assertEqual(sender.sent[0][0], "conn-A")
        self.assertEqual(sender.sent[1][0], "conn-B")

    async def test_no_response_sent_when_handler_returns_no_response(self) -> None:
        handler = _RecordingHandler(result=HandlerResult.no_response())
        registry = HandlerRegistry()
        registry.register(0x0002, handler)
        dispatcher, _, sender = make_dispatcher(registry=registry)

        await dispatcher.dispatch("conn-1", make_message(0x0002))

        self.assertEqual(sender.sent, [])

    async def test_outbound_serial_number_increments_across_responses(self) -> None:
        from src.protocol.parser import PacketParser

        dispatcher, _, sender = make_dispatcher()  # unknown handler always responds
        await dispatcher.dispatch("conn-1", make_message(0x9998, serial_no=1))
        await dispatcher.dispatch("conn-1", make_message(0x9997, serial_no=2))

        parser = PacketParser()
        first = parser.parse(
            sender.sent[0][1][1:-1], received_at=datetime.now(timezone.utc)
        )
        second = parser.parse(
            sender.sent[1][1][1:-1], received_at=datetime.now(timezone.utc)
        )
        self.assertNotEqual(first.serial_no, second.serial_no)


class ConcurrentDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_dispatch_across_connections_all_complete(self) -> None:
        handler = _RecordingHandler()
        registry = HandlerRegistry()
        registry.register(0x0002, handler)
        dispatcher, _, _ = make_dispatcher(registry=registry)

        await asyncio.gather(
            *[
                dispatcher.dispatch(
                    f"conn-{i}",
                    make_message(0x0002, terminal_id="013800138000", serial_no=i),
                )
                for i in range(20)
            ]
        )

        self.assertEqual(len(handler.calls), 20)

    async def test_concurrent_dispatch_serial_numbers_stay_unique(self) -> None:
        dispatcher, _, sender = make_dispatcher()  # unknown handler responds every time

        await asyncio.gather(
            *[
                dispatcher.dispatch(f"conn-{i}", make_message(0x9999, serial_no=i))
                for i in range(30)
            ]
        )

        from src.protocol.parser import PacketParser

        parser = PacketParser()
        serials = [
            parser.parse(frame[1:-1], received_at=datetime.now(timezone.utc)).body[0:2]
            for _, frame in sender.sent
        ]
        # 30 outbound frames, each carrying a distinct *outbound* serial number in the header
        # (not the body's echoed original serial) - check header serial numbers instead.
        header_serials = []
        for _, frame in sender.sent:
            unescaped_minus_delims = frame[1:-1]
            from src.protocol.escaping import unescape

            unescaped = unescape(unescaped_minus_delims)
            header_serials.append(int.from_bytes(unescaped[10:12], "big"))
        self.assertEqual(len(set(header_serials)), 30)


if __name__ == "__main__":
    unittest.main()
