"""`MdvrRegistrationHandler` (`V101` -> `C100`) — the vendor-protocol equivalent of `src.handlers.
registration_handler.TerminalRegistrationHandler`, structurally simpler for a real protocol
reason, not a shortcut: this vendor has no separate authentication message (`docs/vendor/
HARDWARE_ANALYSIS.md` §11) — `V101` both registers *and* is the only identity check that ever
happens, so **this handler binds the `DeviceSession` itself, on success** (`context.device_sessions
.create(...)`), unlike the parent package's `TerminalRegistrationHandler`, which deliberately
leaves session binding to a later, separate `0x0102` authentication handler. There is no MDVR
equivalent of that second message to defer to.

**Rejection closes the connection**, mirroring the parent package's registration handler and the
vendor document's own stated behavior (`docs/vendor/HARDWARE_ANALYSIS.md` §10: an unrecognized
serial number is rejected and "the socket is closed by the center").

`message.device_serial_number` is reused directly as `DeviceSession.terminal_id` — a deliberate
reuse of that field's existing, already-generic role as "the session registry's key," not a
rename (`docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md`'s Decision section).
"""

from __future__ import annotations

from src.logging_setup import get_logger, log_with_fields
from src.vendors.lsz.dispatcher.handler import (
    MdvrHandlerContext,
    MdvrHandlerResult,
    MdvrMessageHandler,
)
from src.vendors.lsz.handlers.provisioning_port import (
    MdvrDeviceProvisioningPort,
    MdvrRegistrationResult,
)
from src.vendors.lsz.protocol.message import MdvrInboundMessage

logger = get_logger("mdvr.handlers.registration")

# docs/vendor/HARDWARE_ANALYSIS.md §10's own documented V101 failure-cause codes.
_FAILURE_CAUSE_UNKNOWN_DEVICE = "2"  # "Illegal Car Serial Number"
_ANSWER_MODE_AUTO = "0"


class MdvrRegistrationHandler(MdvrMessageHandler):
    def __init__(self, provisioning: MdvrDeviceProvisioningPort) -> None:
        self._provisioning = provisioning

    async def handle(
        self, message: MdvrInboundMessage, context: MdvrHandlerContext
    ) -> MdvrHandlerResult:
        authorization = await self._provisioning.authorize_registration(
            device_serial_number=message.device_serial_number
        )
        success = authorization.result == MdvrRegistrationResult.SUCCESS

        log_with_fields(
            logger,
            20 if success else 30,
            "registration_processed",
            connection_id=context.connection_id,
            device_serial_number=message.device_serial_number,
            result=authorization.result.value,
        )

        if not success:
            return MdvrHandlerResult(
                response_keyword="C100",
                response_fields=[
                    "V101",
                    message.sent_at_raw,
                    _ANSWER_MODE_AUTO,
                    "0",
                    _FAILURE_CAUSE_UNKNOWN_DEVICE,
                ],
                close_connection_after=True,
                close_reason=f"registration_rejected:{authorization.result.value}",
            )

        await context.device_sessions.create(
            connection_id=context.connection_id,
            terminal_id=message.device_serial_number,
            device_id=authorization.device_id,
            vehicle_id=authorization.vehicle_id,
            organization_id=authorization.organization_id,
        )

        return MdvrHandlerResult(
            response_keyword="C100",
            response_fields=["V101", message.sent_at_raw, _ANSWER_MODE_AUTO, "1", ""],
        )
