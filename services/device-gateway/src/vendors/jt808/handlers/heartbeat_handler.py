"""`HeartbeatHandler` (`0x0002`, JT/T 808-2013 §8.3). Replaces the `PlaceholderMessageHandler`
this message ID previously fell to (`server.py`'s own `_PLACEHOLDER_HANDLER_NAMES`) — the real
business behavior `placeholder_handler.py`'s own docstring named as a later phase's job: "touch
session" (§8's Handler table).

Acknowledges every heartbeat with the platform general response (`0x8001`, `RESULT_SUCCESS`) —
the standard, uncontroversial JT/T 808-2013 mechanism for this message (no dedicated response
message exists for heartbeat, unlike registration's own `0x8100`), not part of the still-open
`0x0102` auth-code ambiguity `provisioning_port.py` documents; nothing about *how* a device
proves its identity is decided here.

**Promotes `AUTHENTICATED -> ONLINE` on first heartbeat** — reusing the exact same, already-
resolved mechanism `DeviceSessionManager.touch()` establishes (that class's own module
docstring) and mirroring `vendors.lsz.handlers.heartbeat_handler.MdvrHeartbeatHandler`'s
identical role for the sibling vendor: the first `touch()` call after `create()` fires
`on_device_online`, which `Jt808Server`'s own composition root already wires to publish a real
`DeviceOnline` event (device-gateway Redis integration) — this handler needs no knowledge of
that, it only `await`s `touch()`.

A `0x0002` from a `terminal_id` with no bound `DeviceSession` is a safe no-op (`touch()` on an
unknown key does nothing, `DeviceSessionManager.touch`'s own existing behavior) — still
acknowledged with `RESULT_SUCCESS`, since JT/T 808-2013's general-response table (§8.2) has no
"unknown device" result code for the platform to distinguish this case with, the same reasoning
`MdvrHeartbeatHandler` already established for its own vendor's protocol.
"""

from __future__ import annotations

from src.vendors.jt808.dispatcher.general_response import (
    GENERAL_RESPONSE_MESSAGE_ID,
    RESULT_SUCCESS,
    build_general_response_body,
)
from src.vendors.jt808.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.vendors.jt808.protocol.message import InboundMessage


class HeartbeatHandler(MessageHandler):
    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        await context.device_sessions.touch(message.terminal_id)

        body = build_general_response_body(
            original_serial_no=message.serial_no,
            original_message_id=message.message_id,
            result=RESULT_SUCCESS,
        )
        return HandlerResult(
            response_message_id=GENERAL_RESPONSE_MESSAGE_ID, response_body=body
        )
