"""`TerminalRegistrationHandler` (`0x0100`, Phase 9.5; JT808 Technical Design §4/§8, JT/T
808-2013 §8.5/§8.6). Parses the registration body (`registration_body.py`), asks the injected
`DeviceProvisioningPort` to authorize it, and replies `0x8100` (`registration_response.py`)
with the port's decision.

**Rejection closes the connection** — JT808 Technical Design §4, verbatim: "Unknown/duplicate/
unassigned terminal ⇒ registration rejected with the appropriate `0x8100` result code and an
audit entry; the socket is closed." (Real audit-entry writing needs the Business API's
`audit_entries` table — Database persistence, explicitly out of this phase's scope; the
*protocol* behavior — reject, respond, close — is what this handler owns.)

**No session binding on registration** — only `0x0102` authentication creates a `DeviceSession`
(Phase 9.2's `DeviceSessionManager.create`, "after auth" per its own contract). Registration
alone never does; a registered-but-not-yet-authenticated connection has no `DeviceSession`.

A malformed registration body (too short to parse) is not translated into any `0x8100` result
code — none of §8.6's five documented codes mean "malformed" — so `parse_registration_request`
is allowed to raise, and that exception reaches `MessageDispatcher`'s existing handler-error
catch-all (Phase 9.4: logged, no response, connection untouched), rather than this handler
inventing an undocumented sixth result code.
"""

from __future__ import annotations

from src.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.handlers.provisioning_port import DeviceProvisioningPort, RegistrationResult
from src.handlers.registration_body import parse_registration_request
from src.handlers.registration_response import (
    REGISTRATION_RESPONSE_MESSAGE_ID,
    build_registration_response_body,
)
from src.logging_setup import get_logger, log_with_fields
from src.protocol.message import InboundMessage

logger = get_logger("jt808.handlers.registration")


class TerminalRegistrationHandler(MessageHandler):
    def __init__(self, provisioning: DeviceProvisioningPort) -> None:
        self._provisioning = provisioning

    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        request = parse_registration_request(message.body)

        authorization = await self._provisioning.authorize_registration(
            terminal_phone=message.terminal_id, request=request
        )

        log_with_fields(
            logger,
            20 if authorization.result == RegistrationResult.SUCCESS else 30,
            "registration_processed",
            connection_id=context.connection_id,
            terminal_id=message.terminal_id,
            result=authorization.result.value,
        )

        body = build_registration_response_body(
            original_serial_no=message.serial_no,
            result=authorization.result,
            auth_code=authorization.auth_code,
        )

        if authorization.result == RegistrationResult.SUCCESS:
            return HandlerResult(
                response_message_id=REGISTRATION_RESPONSE_MESSAGE_ID, response_body=body
            )

        return HandlerResult(
            response_message_id=REGISTRATION_RESPONSE_MESSAGE_ID,
            response_body=body,
            close_connection_after=True,
            close_reason=f"registration_rejected:{authorization.result.value}",
        )
