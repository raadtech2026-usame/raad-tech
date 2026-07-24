"""`MdvrInboundMessage` — the LSZ MDVR Packet Parser's output, the vendor-protocol equivalent of
`src.protocol.message.InboundMessage`. Dispatch is keyed by `keyword` (an ASCII string like
`"V101"`/`"C100"`), not a binary `message_id`, since this vendor's protocol has no numeric message
identity at all (`docs/vendor/HARDWARE_ANALYSIS.md` §2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MdvrInboundMessage:
    keyword: str
    serial_no: int
    device_serial_number: str
    workstation_serial_number: str | None
    sent_at_raw: str  # "YYMMDD HHMMSS" — left as the raw wire string; handlers that need a
    # parsed datetime decode it themselves (only some messages' semantics need it).
    fields: list[str]  # every field after the common 6-token header, keyword-specific
    declared_length: int  # the frame's own stated content length - informational only, see
    # protocol/framing.py's module docstring on why this is never used for frame boundary
    # detection itself.
    received_at: datetime
