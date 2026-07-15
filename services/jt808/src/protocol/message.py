"""`InboundMessage` — the Packet Parser's output (JT808 Technical Design §6, verbatim skeleton:
"`InboundMessage { message_id, terminal_id, serial_no, body_fields (typed), raw_ref (optional),
received_at }`"). §6's own preamble ("Contracts are language-neutral skeletons... exact byte
layouts are an implementation-time concern") means this is illustrative of the key fields, not
a closed list — `encryption_method` is added here because omitting it would be actively unsafe
(see `header.py`'s module docstring: a future consumer must know a body is RSA-encrypted before
ever attempting to interpret it as plaintext), not because this phase invents new business
scope.

`body` stays untyped `bytes` — the skeleton's "(typed)" describes a *later* phase's job
(message-specific decoding, §8 Handlers), not this one's; renamed from the skeleton's
`body_fields` to `body` precisely to avoid implying decoding that hasn't happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InboundMessage:
    message_id: int
    terminal_id: str
    serial_no: int
    body: bytes
    encryption_method: int
    received_at: datetime
    raw_ref: bytes | None = None
