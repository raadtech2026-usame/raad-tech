"""Outbound frame encoding (Phase 9.4; JT/T 808-2013 §4.4, symmetric counterpart to Phase
9.3's decoder in `parser.py`/`header.py`). Needed because JT808 Technical Design §7's Packet
Dispatcher "ensures the ack is sent" (the automatic `0x8001` general response) — a Dispatcher
responsibility per the approved design, distinct from §12 Command Processing (business-
initiated downlink commands, a later phase).

Builds a complete on-the-wire frame — header + body + checksum, escaped, delimited — mirroring
`header.py`'s decoded fields exactly, in the same order (§4.4.3 Table 2). Fixed-header only
(no subpackage block): every response this phase constructs (the general response, §8.2) fits
comfortably under the single-frame body-length ceiling, so outbound subpackaging is not built.
"""

from __future__ import annotations

from src.protocol.checksum import compute_checksum
from src.protocol.constants import FRAME_DELIMITER
from src.protocol.escaping import escape
from src.protocol.exceptions import MalformedFrameError
from src.protocol.header import encode_bcd_phone

_MAX_BODY_LENGTH = (
    0x03FF  # 10 bits, §4.4.2 Fig. 2 — same ceiling `header.py` decodes against
)


def build_frame(
    *,
    message_id: int,
    terminal_phone: str,
    serial_no: int,
    body: bytes = b"",
    encryption_method: int = 0,
) -> bytes:
    if len(body) > _MAX_BODY_LENGTH:
        raise MalformedFrameError(
            f"Body length {len(body)} exceeds the {_MAX_BODY_LENGTH}-byte protocol ceiling."
        )

    body_attributes = (len(body) & _MAX_BODY_LENGTH) | (
        (encryption_method & 0x07) << 10
    )
    header = bytearray()
    header += message_id.to_bytes(2, "big")
    header += body_attributes.to_bytes(2, "big")
    header += encode_bcd_phone(terminal_phone)
    header += serial_no.to_bytes(2, "big")

    payload = bytes(header) + body
    checksum = compute_checksum(payload)
    return (
        bytes([FRAME_DELIMITER])
        + escape(payload + bytes([checksum]))
        + bytes([FRAME_DELIMITER])
    )
