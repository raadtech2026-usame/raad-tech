"""JT/T 808-2019 message header parsing (confirmed against `mdvrdocs/MDVR-808-1078-spec.pdf`
§4.1 Table 4.1, §4.2 Table 4.2/4.3 — ADR-0025 §2). Fixed 17-byte base layout, big-endian (§4.3:
words/dwords transmitted big-endian), plus an optional 4-byte subpackage block when the body-
attributes subpackage bit is set:

| Offset | Field                | Type    | Notes |
|--------|----------------------|---------|-------|
| 0      | message ID           | WORD    | |
| 2      | body attributes      | WORD    | bit layout below, Table 4.3 |
| 4      | protocol version     | BYTE    | 2019 initial version number is 0x01 |
| 5      | terminal phone       | BCD[10] | 20 packed BCD digits, left-zero-padded |
| 15     | serial no            | WORD    | sender-maintained, cyclic from 0 |
| 17     | total packages       | WORD    | only present if body-attributes bit 13 is set |
| 19     | package sequence     | WORD    | only present if body-attributes bit 13 is set; starts at 1 |

**Body-attributes bit layout (Table 4.3, confirmed verbatim):**
- bits 0-9 (10 bits): body length (max 1023)
- bits 10-12 (3 bits): encryption method — 000 unencrypted, 001 RSA-encrypted, other reserved
- bit 13 (1 bit): subpackage flag
- bit 14 (1 bit): version flag — "JT/T 808-2019 固定为1" (fixed to 1 for 2019). Decoded and
  exposed (`MessageHeader.is_2019_version`) but not enforced — a device sending bit14=0 is not
  rejected by this parser (no approved document specifies that behavior; see module docstring
  discipline elsewhere in this deployable: don't invent validation beyond what's specified).
- bit 15 (1 bit): reserved, should be 0

**This is a straight rework to the 2019 shape, not a dual-mode 2013/2019 parser.** ADR-0025
confirms the procured hardware is JT/T 808-2019; no approved document asks this parser to also
accept 2013-shaped frames, and `vendors/lsz/` remains the fallback adapter for any device that
turns out not to speak this shape.

**This module deliberately parses no message *body* — only the header.** Message-specific body
layouts (§5/§6, e.g. 0x0100 registration, 0x0102 auth, 0x0200 location, JT/T 1078 signaling) are
a Handler's job, not this one's.

**Encryption is recorded, never decrypted.** RSA body decryption is a security/business
capability not built here — `encryption_method` is surfaced on the parsed header/`InboundMessage`
precisely so a later phase never mistakes an encrypted body for plaintext; this phase passes the
(possibly encrypted) body bytes through unexamined either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.vendors.jt808.protocol.exceptions import MalformedFrameError

_HEADER_BASE_LENGTH = 17  # message_id(2) + body_attributes(2) + protocol_version(1) + terminal_phone(10) + serial_no(2)
_SUBPACKAGE_BLOCK_LENGTH = 4  # total_packages(2) + package_sequence(2)
_TERMINAL_PHONE_BYTES = 10
_TERMINAL_PHONE_DIGITS = 20

_BODY_LENGTH_MASK = 0b0000_0011_1111_1111  # bits 0-9
_ENCRYPTION_MASK = 0b0001_1100_0000_0000  # bits 10-12
_ENCRYPTION_SHIFT = 10
_SUBPACKAGE_BIT = 0b0010_0000_0000_0000  # bit 13
_VERSION_FLAG_BIT = 0b0100_0000_0000_0000  # bit 14

JT808_2019_PROTOCOL_VERSION = 0x01  # §4.2 Table 4.2's own stated initial version number


@dataclass(frozen=True)
class MessageHeader:
    message_id: int
    body_length: int
    encryption_method: int
    is_subpackaged: bool
    protocol_version: int
    is_2019_version: bool
    terminal_phone: str
    serial_no: int
    total_packages: int | None
    package_sequence: int | None


def encode_bcd_phone(terminal_phone: str) -> bytes:
    """20 decimal digits -> BCD[10] (the encode-side mirror of `_decode_bcd_phone`, needed to
    address outbound response/command frames back to the same terminal, Table 4.2)."""
    if len(terminal_phone) != _TERMINAL_PHONE_DIGITS or not terminal_phone.isdigit():
        raise MalformedFrameError(
            f"terminal_phone must be exactly {_TERMINAL_PHONE_DIGITS} decimal digits: "
            f"{terminal_phone!r}."
        )
    result = bytearray()
    for i in range(0, _TERMINAL_PHONE_DIGITS, 2):
        high, low = int(terminal_phone[i]), int(terminal_phone[i + 1])
        result.append((high << 4) | low)
    return bytes(result)


def _decode_bcd_phone(data: bytes) -> str:
    """BCD[10] -> 20 decimal digits (§4.2's packed-BCD convention: each nibble one decimal
    digit, most-significant nibble first per byte, most-significant byte first)."""
    digits = []
    for byte in data:
        high, low = (byte >> 4) & 0x0F, byte & 0x0F
        if high > 9 or low > 9:
            raise MalformedFrameError(
                f"Invalid BCD nibble in terminal phone byte 0x{byte:02x}."
            )
        digits.append(str(high))
        digits.append(str(low))
    return "".join(digits)


def parse_header(data: bytes) -> tuple[MessageHeader, int]:
    """Returns `(header, header_length)` — `header_length` is the byte offset where the body
    begins (17, or 21 if subpackaged), so the caller (`parser.py`) knows where to slice.
    """
    if len(data) < _HEADER_BASE_LENGTH:
        raise MalformedFrameError(
            f"Frame shorter than the {_HEADER_BASE_LENGTH}-byte header base "
            f"({len(data)} bytes)."
        )

    message_id = int.from_bytes(data[0:2], "big")
    body_attributes = int.from_bytes(data[2:4], "big")
    body_length = body_attributes & _BODY_LENGTH_MASK
    encryption_method = (body_attributes & _ENCRYPTION_MASK) >> _ENCRYPTION_SHIFT
    is_subpackaged = bool(body_attributes & _SUBPACKAGE_BIT)
    is_2019_version = bool(body_attributes & _VERSION_FLAG_BIT)
    protocol_version = data[4]
    terminal_phone = _decode_bcd_phone(data[5 : 5 + _TERMINAL_PHONE_BYTES])
    serial_no = int.from_bytes(data[15:17], "big")

    header_length = _HEADER_BASE_LENGTH
    total_packages: int | None = None
    package_sequence: int | None = None
    if is_subpackaged:
        if len(data) < header_length + _SUBPACKAGE_BLOCK_LENGTH:
            raise MalformedFrameError(
                "Subpackage bit set but frame is too short for the 4-byte subpackage block."
            )
        total_packages = int.from_bytes(data[header_length : header_length + 2], "big")
        package_sequence = int.from_bytes(
            data[header_length + 2 : header_length + 4], "big"
        )
        header_length += _SUBPACKAGE_BLOCK_LENGTH

    header = MessageHeader(
        message_id=message_id,
        body_length=body_length,
        encryption_method=encryption_method,
        is_subpackaged=is_subpackaged,
        protocol_version=protocol_version,
        is_2019_version=is_2019_version,
        terminal_phone=terminal_phone,
        serial_no=serial_no,
        total_packages=total_packages,
        package_sequence=package_sequence,
    )
    return header, header_length
