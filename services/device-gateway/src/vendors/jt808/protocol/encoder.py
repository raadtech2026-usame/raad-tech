"""Outbound frame encoding (JT/T 808-2019 §4, symmetric counterpart to the decoder in
`parser.py`/`header.py`). Needed because JT808 Technical Design §7's Packet Dispatcher "ensures
the ack is sent" (the automatic `0x8001` general response) — a Dispatcher responsibility per the
approved design — and, since the JT808 device-plane integration gap / ADR-0024 command-downlink
work, for platform-initiated commands too (`handlers/command_downlink.py`).

Builds a complete on-the-wire frame — header + body + checksum, escaped, delimited — mirroring
`header.py`'s decoded fields exactly, in the same order (§4.2 Table 4.2). Fixed-header only
(no subpackage block): every response/command this deployable constructs fits comfortably under
the single-frame body-length ceiling, so outbound subpackaging is not built.
"""

from __future__ import annotations

from src.vendors.jt808.protocol.checksum import compute_checksum
from src.vendors.jt808.protocol.constants import FRAME_DELIMITER
from src.vendors.jt808.protocol.escaping import escape
from src.vendors.jt808.protocol.exceptions import MalformedFrameError
from src.vendors.jt808.protocol.header import JT808_2019_PROTOCOL_VERSION, encode_bcd_phone

_MAX_BODY_LENGTH = (
    0x03FF  # 10 bits, §4.2 Table 4.3 — same ceiling `header.py` decodes against
)
_VERSION_FLAG_BIT = 0b0100_0000_0000_0000  # bit 14, Table 4.3: "JT/T 808-2019 固定为1"


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

    body_attributes = (
        (len(body) & _MAX_BODY_LENGTH)
        | ((encryption_method & 0x07) << 10)
        | _VERSION_FLAG_BIT
    )
    header = bytearray()
    header += message_id.to_bytes(2, "big")
    header += body_attributes.to_bytes(2, "big")
    header += bytes([JT808_2019_PROTOCOL_VERSION])
    header += encode_bcd_phone(terminal_phone)
    header += serial_no.to_bytes(2, "big")

    payload = bytes(header) + body
    checksum = compute_checksum(payload)
    return (
        bytes([FRAME_DELIMITER])
        + escape(payload + bytes([checksum]))
        + bytes([FRAME_DELIMITER])
    )
