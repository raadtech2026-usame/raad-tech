"""Terminal Registration (`0x0100`) body parsing — JT/T 808-2019 shape, confirmed against
`mdvrdocs/MDVR-808-1078-spec.pdf` §5.1.5 Table 5.3 (ADR-0025 §2):

| Offset | Field           | Type     | Notes |
|--------|-----------------|----------|-------|
| 0      | province ID     | WORD     | GB/T 2260 first 2 digits; 0 reserved, platform default |
| 2      | city/county ID  | WORD     | GB/T 2260 last 4 digits; 0 reserved, platform default |
| 4      | manufacturer ID | BYTE[11] | uppercase letters + digits, manufacturer-assigned, null-padded |
| 15     | terminal model  | BYTE[30] | uppercase letters + digits, manufacturer-defined, null-padded ("不足位后补0x00") |
| 45     | terminal ID     | BYTE[30] | uppercase letters + digits; null-padded, same convention |
| 75     | plate color     | BYTE     | Table 5.4 (JT/T 697.7-2014 表7); 0 = not yet plated |
| 76     | vehicle ID      | STRING   | issued plate number if plated, else VIN per project agreement (GBK, §4.2) |

Widened from the 2013 shape (`manufacturer ID BYTE[5]`, `terminal model BYTE[20]`,
`terminal ID BYTE[7]`, fixed portion 37 bytes) to the confirmed 2019 shape (fixed portion 76
bytes) — JT808 device-plane field-width rework, ADR-0025 §2.

**This body's `terminal ID` (offset 45, manufacturer-assigned, `BYTE[30]`) is a completely
different identifier from `InboundMessage.terminal_id`** (the header's `BCD[10]` terminal
phone, §4.2) — same English name in the spec's own vocabulary, two unrelated fields. Named
`manufacturer_terminal_id` here specifically to avoid that collision; every other module in
this codebase's `terminal_id` always means the header's phone-based identity.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.vendors.jt808.protocol.exceptions import MalformedFrameError
from src.vendors.jt808.protocol.strings import decode_gbk_string

_FIXED_BODY_LENGTH = 76  # everything up to and including plate_color


@dataclass(frozen=True)
class RegistrationRequest:
    province_id: int
    city_county_id: int
    manufacturer_id: bytes
    terminal_model: str
    manufacturer_terminal_id: str
    plate_color: int
    vehicle_identifier: str


def _strip_null_padding(data: bytes) -> str:
    return data.rstrip(b"\x00").decode("ascii", errors="replace")


def parse_registration_request(body: bytes) -> RegistrationRequest:
    if len(body) < _FIXED_BODY_LENGTH:
        raise MalformedFrameError(
            f"Registration body shorter than the {_FIXED_BODY_LENGTH}-byte fixed portion "
            f"({len(body)} bytes)."
        )

    province_id = int.from_bytes(body[0:2], "big")
    city_county_id = int.from_bytes(body[2:4], "big")
    manufacturer_id = body[4:15]
    terminal_model = _strip_null_padding(body[15:45])
    manufacturer_terminal_id = _strip_null_padding(body[45:75])
    plate_color = body[75]
    vehicle_identifier = decode_gbk_string(body[76:])

    return RegistrationRequest(
        province_id=province_id,
        city_county_id=city_county_id,
        manufacturer_id=manufacturer_id,
        terminal_model=terminal_model,
        manufacturer_terminal_id=manufacturer_terminal_id,
        plate_color=plate_color,
        vehicle_identifier=vehicle_identifier,
    )
