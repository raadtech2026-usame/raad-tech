"""MessageDispatcher tests (Phase 9.4): known message dispatch, unknown message dispatch,
handler exception containment, concurrent dispatch, response propagation.
"""

import asyncio
import unittest
from datetime import datetime, timezone

from src.vendors.jt808.dispatcher.dispatcher import MessageDispatcher
from src.vendors.jt808.dispatcher.general_response import (
    GENERAL_RESPONSE_MESSAGE_ID,
    RESULT_NOT_SUPPORTED,
)
from src.vendors.jt808.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.vendors.jt808.dispatcher.registry import HandlerRegistry
from src.vendors.jt808.dispatcher.unknown_handler import UnknownMessageHandler
from src.vendors.jt808.protocol.message import InboundMessage
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry


def make_message(
    message_id: int, terminal_id: str = "00000000013800138000", serial_no: int = 1
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


class _CancellingHandler(MessageHandler):
    async def handle(self, message, context) -> HandlerResult:
        raise asyncio.CancelledError()


class _RaisingSender:
    """A `send` callable that always fails — for asserting the observability-only send-path
    logging (JT808 post-0x0102 investigation, 2026-09-15) preserves the exact prior control
    flow (the exception still propagates out of `dispatch()` uncaught) rather than swallowing
    it, unlike an ordinary handler exception."""

    async def __call__(self, connection_id: str, data: bytes) -> None:
        raise ConnectionResetError("send failed")


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
        from src.vendors.jt808.protocol.parser import PacketParser

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


class HandlerCancellationTests(unittest.IsolatedAsyncioTestCase):
    """Regression coverage for the JT808 post-0x0102 investigation (2026-09-15): unlike an
    ordinary handler exception (`HandlerExceptionTests`, above), a cancellation must never be
    swallowed — `except Exception` never catches `asyncio.CancelledError` (a `BaseException`
    since Python 3.8), and this dispatcher must not accidentally start doing so either."""

    async def test_cancelled_error_is_re_raised_not_swallowed(self) -> None:
        registry = HandlerRegistry()
        registry.register(0x0002, _CancellingHandler())
        dispatcher, _, _ = make_dispatcher(registry=registry)

        with self.assertRaises(asyncio.CancelledError):
            await dispatcher.dispatch("conn-1", make_message(0x0002))

    async def test_cancelled_error_logs_handler_cancelled_with_identifying_fields(self) -> None:
        registry = HandlerRegistry()
        registry.register(0x0002, _CancellingHandler())
        dispatcher, _, _ = make_dispatcher(registry=registry)

        with self.assertLogs("jt808.dispatcher", level="WARNING") as captured:
            with self.assertRaises(asyncio.CancelledError):
                await dispatcher.dispatch(
                    "conn-1", make_message(0x0002, terminal_id="00000000014482607571")
                )

        # `log_with_fields` puts structured data in `record.extra_fields` (see
        # `logging_setup.log_with_fields`) — `assertLogs`'s own `.output` only ever renders
        # `record.getMessage()`, so the field values must be asserted on `.records` directly.
        record = next(r for r in captured.records if r.getMessage() == "handler_cancelled")
        self.assertEqual(record.extra_fields["connection_id"], "conn-1")
        self.assertEqual(record.extra_fields["terminal_id"], "00000000014482607571")
        self.assertEqual(record.extra_fields["message_id"], "0x0002")

    async def test_cancelled_error_sends_no_response(self) -> None:
        registry = HandlerRegistry()
        registry.register(0x0002, _CancellingHandler())
        dispatcher, _, sender = make_dispatcher(registry=registry)

        with self.assertRaises(asyncio.CancelledError):
            await dispatcher.dispatch("conn-1", make_message(0x0002))

        self.assertEqual(sender.sent, [])


class ResponseSendObservabilityTests(unittest.IsolatedAsyncioTestCase):
    """Regression coverage for the JT808 post-0x0102 investigation (2026-09-15): before this,
    an outbound response frame (e.g. 0x8100/0x8001) had no logging at all around the send, so
    a silent delivery failure was indistinguishable from a successful one in the logs."""

    async def test_successful_send_logs_response_frame_sent(self) -> None:
        handler = _RecordingHandler(
            result=HandlerResult(
                response_message_id=0x8001, response_body=b"\x00\x01\x00\x02\x00"
            )
        )
        registry = HandlerRegistry()
        registry.register(0x0002, handler)
        dispatcher, _, _ = make_dispatcher(registry=registry)

        with self.assertLogs("jt808.dispatcher", level="DEBUG") as captured:
            await dispatcher.dispatch(
                "conn-1", make_message(0x0002, terminal_id="00000000014482607571")
            )

        record = next(
            r for r in captured.records if r.getMessage() == "response_frame_sent"
        )
        self.assertEqual(record.extra_fields["connection_id"], "conn-1")
        self.assertEqual(record.extra_fields["terminal_id"], "00000000014482607571")
        self.assertEqual(record.extra_fields["message_id"], "0x0002")
        self.assertEqual(record.extra_fields["response_message_id"], "0x8001")

    async def test_session_establishment_replies_are_logged_at_info_with_result_code(
        self,
    ) -> None:
        """2026-09-17: the `0x8100`/`0x8001` answering a registration or authentication must be
        visible at the default INFO level, with its result code, because it is the first thing
        to check when a terminal connects but never comes online."""
        cases = (
            (0x0100, 0x8100, b"\x00\x07\x00" + "SECRET-AUTH-CODE".encode("gbk"), 0),
            (0x0102, 0x8001, b"\x00\x08\x01\x02\x01", 1),
        )
        for inbound_id, response_id, body, expected_result in cases:
            registry = HandlerRegistry()
            registry.register(
                inbound_id,
                _RecordingHandler(
                    result=HandlerResult(response_message_id=response_id, response_body=body)
                ),
            )
            dispatcher, _, _ = make_dispatcher(registry=registry)

            with self.assertLogs("jt808.dispatcher", level="INFO") as captured:
                await dispatcher.dispatch("conn-1", make_message(inbound_id))

            record = next(
                r for r in captured.records if r.getMessage() == "response_frame_sent"
            )
            self.assertEqual(record.levelname, "INFO")
            self.assertEqual(record.extra_fields["result"], expected_result)
            self.assertEqual(record.extra_fields["response_message_id"], f"0x{response_id:04x}")
            self.assertIn("response_serial_no", record.extra_fields)
            # Only the result byte is ever logged — never the body, which for 0x8100 carries the
            # plaintext auth code.
            self.assertNotIn("SECRET-AUTH-CODE", repr(record.__dict__))

    async def test_per_message_acknowledgements_stay_at_debug(self) -> None:
        """Heartbeat/location acknowledgements are one per message, so they stay at DEBUG and
        do not flood the default INFO log."""
        registry = HandlerRegistry()
        registry.register(
            0x0200,
            _RecordingHandler(
                result=HandlerResult(
                    response_message_id=0x8001, response_body=b"\x00\x01\x02\x00\x00"
                )
            ),
        )
        dispatcher, _, _ = make_dispatcher(registry=registry)

        with self.assertLogs("jt808.dispatcher", level="DEBUG") as captured:
            await dispatcher.dispatch("conn-1", make_message(0x0200))

        record = next(r for r in captured.records if r.getMessage() == "response_frame_sent")
        self.assertEqual(record.levelname, "DEBUG")
        self.assertEqual(record.extra_fields["result"], 0)

    async def test_failed_send_logs_response_frame_send_failed_and_still_raises(self) -> None:
        handler = _RecordingHandler(
            result=HandlerResult(
                response_message_id=0x8100, response_body=b"\x00\x01\x00\x02\x00"
            )
        )
        registry = HandlerRegistry()
        registry.register(0x0100, handler)
        dispatcher, _, _ = make_dispatcher(registry=registry, sender=_RaisingSender())

        with self.assertLogs("jt808.dispatcher", level="ERROR") as captured:
            with self.assertRaises(ConnectionResetError):
                await dispatcher.dispatch(
                    "conn-1", make_message(0x0100, terminal_id="00000000014482607571")
                )

        record = next(
            r for r in captured.records if r.getMessage() == "response_frame_send_failed"
        )
        self.assertEqual(record.extra_fields["connection_id"], "conn-1")
        self.assertEqual(record.extra_fields["terminal_id"], "00000000014482607571")
        self.assertEqual(record.extra_fields["message_id"], "0x0100")
        self.assertEqual(record.extra_fields["response_message_id"], "0x8100")
        self.assertIn("send failed", record.extra_fields["error"])


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
            "conn-A", make_message(0x0002, terminal_id="00000000013800138000")
        )
        await dispatcher.dispatch(
            "conn-B", make_message(0x0002, terminal_id="00000000013900139000")
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
        from src.vendors.jt808.protocol.parser import PacketParser

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
                    make_message(0x0002, terminal_id="00000000013800138000", serial_no=i),
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

        from src.vendors.jt808.protocol.parser import PacketParser

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
            from src.vendors.jt808.protocol.escaping import unescape

            unescaped = unescape(unescaped_minus_delims)
            header_serials.append(int.from_bytes(unescaped[15:17], "big"))
        self.assertEqual(len(set(header_serials)), 30)


if __name__ == "__main__":
    unittest.main()
