"""`TerminalAuthenticationHandler` (`0x0102`, Phase 9.5; JT808 Technical Design §4/§5/§8, JT/T
808-2013 §8.8). Decodes the auth code (§4.2: `STRING`, GBK), asks the injected
`DeviceProvisioningPort` to verify it, and replies via the general response (`0x8001`,
`dispatcher/general_response.py` — Phase 9.4 infrastructure, reused as-is: §8's handler table
says Auth replies `0x8001`, not a dedicated message type the way Registration's `0x8100` is).

**On success:** binds the session — `context.device_sessions.create(...)` (Phase 9.2's
`DeviceSessionManager`, "after auth" per its own contract) — this *is* "session binding after
successful authentication," this phase's own scope item. The resulting `DeviceSession` is
created in `AUTHENTICATED` state; per the resolved Phase 9.2 conflict (confirmed with the user
in that phase) and reconfirmed for this phase, promotion to `ONLINE` requires the *first*
`touch()` — a heartbeat/location event this phase does not process (a future Heartbeat
Processing phase's job) — so this handler deliberately does not call `touch()` itself. This is
"device online transition (following the approved state machine)" correctly implemented by
*not* skipping ahead of it.

**Duplicate/repeated authentication is not new logic here — it reuses Phase 9.2 entirely.**
`create()` already implements ADR-808-8 (newest authenticated connection wins) for a *different*
connection presenting the same `terminal_id`, and is a safe idempotent no-op-ish replace for
the *same* connection re-authenticating (Phase 9.2's own `previous.connection_id != connection_
id` guard against self-supersede) — exactly what happens if a device retries `0x0102` after not
receiving `0x8001` in time (JT/T 808-2013 §6.1.2's retry-on-timeout mechanics). This handler
re-verifies the auth code on every `0x0102` it receives, every time, rather than trusting a
prior success — a stale/replayed auth code is rejected even on a connection that authenticated
moments ago.

**Failure closes the connection** — JT808 Technical Design §4, verbatim: "Authentication
(`0x0102`): the presented auth code is verified... Failure ⇒ reject + audit + close." Applies
uniformly whether the code is simply wrong or the `terminal_id` was never registered (this
handler does not distinguish "invalid code" from "unknown terminal" in its own response — both
reach `DeviceProvisioningPort.verify_auth_code` and get `is_valid=False`; the general
response's `RESULT_FAILURE` code is the only one JT/T 808-2013 §8.2 defines for this case).
"""

from __future__ import annotations

from src.dispatcher.general_response import (
    GENERAL_RESPONSE_MESSAGE_ID,
    RESULT_FAILURE,
    RESULT_SUCCESS,
    build_general_response_body,
)
from src.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.handlers.provisioning_port import DeviceProvisioningPort
from src.logging_setup import get_logger, log_with_fields
from src.protocol.message import InboundMessage
from src.protocol.strings import decode_gbk_string

logger = get_logger("jt808.handlers.authentication")


class TerminalAuthenticationHandler(MessageHandler):
    def __init__(self, provisioning: DeviceProvisioningPort) -> None:
        self._provisioning = provisioning

    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        auth_code = decode_gbk_string(message.body)

        result = await self._provisioning.verify_auth_code(
            terminal_phone=message.terminal_id, auth_code=auth_code
        )

        if not result.is_valid:
            log_with_fields(
                logger,
                30,
                "authentication_failed",
                connection_id=context.connection_id,
                terminal_id=message.terminal_id,
            )
            body = build_general_response_body(
                original_serial_no=message.serial_no,
                original_message_id=message.message_id,
                result=RESULT_FAILURE,
            )
            return HandlerResult(
                response_message_id=GENERAL_RESPONSE_MESSAGE_ID,
                response_body=body,
                close_connection_after=True,
                close_reason="authentication_failed",
            )

        await context.device_sessions.create(
            connection_id=context.connection_id,
            terminal_id=message.terminal_id,
            device_id=result.device_id,
            vehicle_id=result.vehicle_id,
            organization_id=result.organization_id,
        )
        log_with_fields(
            logger,
            20,
            "authentication_succeeded",
            connection_id=context.connection_id,
            terminal_id=message.terminal_id,
        )
        body = build_general_response_body(
            original_serial_no=message.serial_no,
            original_message_id=message.message_id,
            result=RESULT_SUCCESS,
        )
        return HandlerResult(
            response_message_id=GENERAL_RESPONSE_MESSAGE_ID, response_body=body
        )
