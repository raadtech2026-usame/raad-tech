"""JT/T 808-2013 message header parsing (§4.4.3, Table 2 + Fig. 2). Fixed 12-byte base layout,
big-endian (§4.3: "协议采用大端模式(big-endian)的网络字节序来传递字和双字" — words/dwords
transmitted big-endian), plus an optional 4-byte subpackage block when the body-attributes
subpackage bit is set:

| Offset | Field                | Type    | Notes |
|--------|----------------------|---------|-------|
| 0      | message ID           | WORD    | |
| 2      | body attributes      | WORD    | bit layout below |
| 4      | terminal phone       | BCD[6]  | 12 packed BCD digits — §5's decoding note |
| 10     | serial no            | WORD    | |
| 12     | total packages       | WORD    | only present if body-attributes bit 13 is set |
| 14     | package sequence     | WORD    | only present if body-attributes bit 13 is set; starts at 1 |

**Body-attributes bit layout (§4.4.2 Fig. 2, cross-checked against the prose immediately
below it, which explicitly names bits 10-12 and bit 13 — the diagram's column order for the
remaining two labels then fixes bits 0-9 and 14-15 unambiguously):**
- bits 0-9 (10 bits): body length (max 1023 — a real protocol ceiling, distinct from
  `protocol/framing.py`'s `max_frame_size`, which is this service's own defensive buffer cap)
- bits 10-12 (3 bits): encryption method — prose verbatim: "bit10~bit12 为数据加密标识位；当此
  三位都为0，表示消息体不加密；当第10位为1，表示消息体经过RSA算法加密；其他保留" ("bits
  10-12 are the encryption flag; all-zero means unencrypted; bit 10 = 1 means RSA-encrypted;
  other combinations reserved")
- bit 13 (1 bit): subpackage flag — prose verbatim: "当消息体属性中第13位为1时表示消息体为长
  消息，进行分包发送处理" ("when bit 13 is 1, the body is a long message, sent as subpackages")
- bits 14-15 (2 bits): reserved

**Terminal phone decoding (§4.4.3 Table 2's own note, restated at §5):** "根据安装后终端自身的
手机号转换。手机号不足12位，则在前补充数字" — the BCD[6] field is the terminal's own phone
number, left-zero-padded to 12 digits by the terminal itself; this parser only decodes the 6
packed-BCD bytes into their 12 decimal digits (each byte = 2 digits, per §4.2's "BCD[n]: 8421
码" = standard packed BCD), it does not (and cannot) recover which padding convention the
terminal applied.

**This module deliberately parses no message *body* — only the header.** Message-specific body
layouts (§8, e.g. 0x0100 registration, 0x0102 auth, 0x0200 location) are a Handler's job
(JT808 Technical Design §8), a later phase.

**Encryption is recorded, never decrypted.** RSA body decryption is a security/business
capability this phase does not build (no key material, no RSA implementation) — `encryption_
method` is surfaced on the parsed header/`InboundMessage` precisely so a later phase never
mistakes an encrypted body for plaintext; this phase passes the (possibly encrypted) body
bytes through unexamined either way.

**2013 edition only.** The attached primary spec is JT/T 808-2013; this parser does not attempt
JT/T 808-2019 compatibility (different terminal-ID width/scheme — flagged as a [PROPOSED],
not-yet-adopted delta in the unadopted Device Plane draft's own ADR-808-3 discussion). Vendor/
edition detection is the Anti-Corruption Layer's job (Phase 2 §5.1, Backend LLD §6's vendor
ACL), not this base parser's.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.protocol.exceptions import MalformedFrameError

_HEADER_BASE_LENGTH = (
    12  # message_id(2) + body_attributes(2) + terminal_phone(6) + serial_no(2)
)
_SUBPACKAGE_BLOCK_LENGTH = 4  # total_packages(2) + package_sequence(2)

_BODY_LENGTH_MASK = 0b0000_0011_1111_1111  # bits 0-9
_ENCRYPTION_MASK = 0b0001_1100_0000_0000  # bits 10-12
_ENCRYPTION_SHIFT = 10
_SUBPACKAGE_BIT = 0b0010_0000_0000_0000  # bit 13


@dataclass(frozen=True)
class MessageHeader:
    message_id: int
    body_length: int
    encryption_method: int
    is_subpackaged: bool
    terminal_phone: str
    serial_no: int
    total_packages: int | None
    package_sequence: int | None


def _decode_bcd_phone(data: bytes) -> str:
    """BCD[6] -> 12 decimal digits (§4.2: "BCD[n]: 8421 码, n 字节" — standard packed BCD, each
    nibble one decimal digit, most-significant nibble first per byte, most-significant byte
    first per §4.3's big-endian convention)."""
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
    begins (12, or 16 if subpackaged), so the caller (`parser.py`) knows where to slice.
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
    terminal_phone = _decode_bcd_phone(data[4:10])
    serial_no = int.from_bytes(data[10:12], "big")

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
        terminal_phone=terminal_phone,
        serial_no=serial_no,
        total_packages=total_packages,
        package_sequence=package_sequence,
    )
    return header, header_length
