"""`MdvrHeartbeatHandler` (`V109` -> `C501`). `docs/vendor/HARDWARE_ANALYSIS.md`'s own Commands
table (§9) flags `V109` as serving double duty across the vendor's two source documents: the
primary protocol document describes `C501` only as a center-initiated, unprompted "once every 6s"
heartbeat, while the supplementary packet-capture document's own worked example shows `C501` sent
as the direct acknowledgment to a device's `V109` heartbeat. This handler follows the
supplementary document's concrete, captured-traffic example (the more directly authoritative
source for actual wire behavior) — acknowledging every `V109` with a `C501` — and does **not**
additionally implement a background timer proactively sending `C501` to every connected device
every 6 seconds regardless of activity; that is a distinct, not-yet-built feature, flagged here
rather than silently assumed equivalent.

**Promotes `AUTHENTICATED -> ONLINE` on first heartbeat** — reusing the exact same, already-
resolved open item the parent package's own `DeviceSessionManager.touch()` establishes (see that
class's own module docstring): the first `touch()` call after `create()` fires `on_device_online`.
No change needed to that class for this vendor's protocol to drive the same transition.

A `V109` from a serial number with no bound `DeviceSession` is a no-op (`touch()` on an unknown key
does nothing) rather than an error — mirroring `DeviceSessionManager.touch()`'s own existing,
already-safe behavior; nothing new to guard here.
"""

from __future__ import annotations

from src.vendors.lsz_mdvr.dispatcher.handler import (
    MdvrHandlerContext,
    MdvrHandlerResult,
    MdvrMessageHandler,
)
from src.vendors.lsz_mdvr.protocol.message import MdvrInboundMessage


class MdvrHeartbeatHandler(MdvrMessageHandler):
    async def handle(
        self, message: MdvrInboundMessage, context: MdvrHandlerContext
    ) -> MdvrHandlerResult:
        context.device_sessions.touch(message.device_serial_number)
        return MdvrHandlerResult(response_keyword="C501", response_fields=[])
