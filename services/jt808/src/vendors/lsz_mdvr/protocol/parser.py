"""LSZ MDVR message parser — decodes a raw frame from `framing.MdvrFrameBuffer` (bytes starting
with `$$dc`, up to but excluding the terminating `#`) into an `MdvrInboundMessage`.

Every signaling-channel command shares the same 6-token common header (per every worked example
in `mdvrdocs/mdvr网络通信协议V0.00.30_150103 - 英文.doc` and its supplementary document):
`$$dc<length>,<seq>,<keyword>,<device_serial_number>,<workstation_serial_number>,<sent_at>,
<keyword-specific fields...>`. `sent_at` ("YYMMDD HHMMSS") itself contains a literal space but no
comma, so a plain comma split does not fragment it.

**Comma-splitting is not fully general** — the vendor document itself warns that some fields
(failure-cause descriptions, alarm names) "may themselves contain a comma," which a naive split
cannot handle correctly. None of the messages this parser is built for (`V101`, `V109`, `V114`,
`C100`, `C501`) carry such a field in their documented shape, so this is a deliberate, scoped
limitation, not an oversight — flagged here so a future extension to a message type that does
carry free-text doesn't rediscover this as a silent parsing bug.
"""

from __future__ import annotations

from datetime import datetime

from src.vendors.lsz_mdvr.protocol.exceptions import MdvrMalformedMessageError
from src.vendors.lsz_mdvr.protocol.message import MdvrInboundMessage

_START_MARKER = "$$dc"
_COMMON_HEADER_TOKEN_COUNT = 6  # length, seq, keyword, device_serial, workstation_serial, sent_at


def parse_frame(raw_frame: bytes, *, received_at: datetime) -> MdvrInboundMessage:
    text = raw_frame.decode("ascii", errors="replace")
    if not text.startswith(_START_MARKER):
        raise MdvrMalformedMessageError(
            f"Frame does not start with '{_START_MARKER}': {text[:16]!r}"
        )
    content = text[len(_START_MARKER) :]
    tokens = content.split(",")
    if len(tokens) < _COMMON_HEADER_TOKEN_COUNT:
        raise MdvrMalformedMessageError(
            f"Frame has {len(tokens)} tokens, fewer than the "
            f"{_COMMON_HEADER_TOKEN_COUNT}-token common header requires."
        )

    declared_length_token, serial_no_token, keyword, device_serial_number = tokens[0:4]
    workstation_serial_number = tokens[4] or None
    sent_at_raw = tokens[5]
    fields = tokens[_COMMON_HEADER_TOKEN_COUNT:]

    if not keyword:
        raise MdvrMalformedMessageError("Empty command keyword in frame.")
    if not device_serial_number:
        raise MdvrMalformedMessageError("Empty device serial number in frame.")

    try:
        declared_length = int(declared_length_token)
    except ValueError as exc:
        raise MdvrMalformedMessageError(
            f"Non-numeric declared length {declared_length_token!r}."
        ) from exc
    try:
        serial_no = int(serial_no_token)
    except ValueError as exc:
        raise MdvrMalformedMessageError(
            f"Non-numeric transmission serial number {serial_no_token!r}."
        ) from exc

    return MdvrInboundMessage(
        keyword=keyword,
        serial_no=serial_no,
        device_serial_number=device_serial_number,
        workstation_serial_number=workstation_serial_number,
        sent_at_raw=sent_at_raw,
        fields=fields,
        declared_length=declared_length,
        received_at=received_at,
    )
