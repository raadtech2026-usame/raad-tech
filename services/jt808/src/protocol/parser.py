"""JT/T 808-2013 Packet Parser (JT808 Technical Design §6). Consumes one raw frame from Phase
9.1's `FrameBuffer` (delimiters already stripped, still escaped) and produces a validated
`InboundMessage` — or `None` if the frame was a non-final subpackage still awaiting the rest
(`reassembly.py`).

**Pipeline, in the exact order §4.4.2 specifies for receiving** ("转义还原->验证校验码->解析
消息" — unescape -> verify checksum -> parse message, `escaping.py`'s module docstring):
unescape the whole frame -> split off the trailing 1-byte checksum -> verify it over what
remains (header+body) -> parse the header -> slice the body to the header's declared length ->
if subpackaged, feed the reassembler.

Malformed frames (checksum mismatch, truncated header, invalid escape sequence, short body)
raise a typed `ProtocolError` subclass rather than crashing the connection — Backend LLD §6:
"Malformed/checksum-fail frames are dropped + counted + logged (never crash the connection)."
Counting/logging the drop and deciding what to do next is the caller's job (`server.py`'s
`on_frame` wiring) — this parser only ever raises or returns, never logs a business decision
itself.
"""

from __future__ import annotations

from datetime import datetime

from src.protocol.checksum import compute_checksum, verify_checksum
from src.protocol.escaping import unescape
from src.protocol.exceptions import ChecksumError, MalformedFrameError
from src.protocol.header import parse_header
from src.protocol.message import InboundMessage
from src.protocol.reassembly import MessageReassembler


class PacketParser:
    def __init__(self, *, reassembler: MessageReassembler | None = None) -> None:
        self._reassembler = reassembler or MessageReassembler()

    def parse(
        self, raw_frame: bytes, *, received_at: datetime
    ) -> InboundMessage | None:
        unescaped = unescape(raw_frame)
        if len(unescaped) < 1:
            raise MalformedFrameError("Empty frame after unescaping.")

        payload, checksum_byte = unescaped[:-1], unescaped[-1]
        if not verify_checksum(payload, checksum_byte):
            raise ChecksumError(
                f"Checksum mismatch: computed=0x{compute_checksum(payload):02x} "
                f"expected=0x{checksum_byte:02x}."
            )

        header, header_length = parse_header(payload)
        body = payload[header_length : header_length + header.body_length]
        if len(body) != header.body_length:
            raise MalformedFrameError(
                f"Body length mismatch: header declares {header.body_length} bytes, "
                f"only {len(body)} available."
            )

        if header.is_subpackaged:
            assert header.total_packages is not None
            assert header.package_sequence is not None
            complete_body = self._reassembler.add_part(
                terminal_id=header.terminal_phone,
                message_id=header.message_id,
                total_packages=header.total_packages,
                package_sequence=header.package_sequence,
                body=body,
            )
            if complete_body is None:
                return None  # awaiting more subpackages
            body = complete_body

        return InboundMessage(
            message_id=header.message_id,
            terminal_id=header.terminal_phone,
            serial_no=header.serial_no,
            body=body,
            encryption_method=header.encryption_method,
            received_at=received_at,
            raw_ref=raw_frame,
        )
