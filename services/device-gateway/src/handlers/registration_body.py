"""Terminal Registration (`0x0100`) body parsing — JT/T 808-2013 §8.5 Table 7, verbatim:

| Offset | Field           | Type     | Notes |
|--------|-----------------|----------|-------|
| 0      | province ID     | WORD     | 0 reserved, platform uses its own default |
| 2      | city/county ID  | WORD     | 0 reserved, platform uses its own default |
| 4      | manufacturer ID | BYTE[5]  | opaque, manufacturer-assigned |
| 9      | terminal model  | BYTE[20] | manufacturer-defined; null-padded ("位数不足时，后补0X00") |
| 29     | terminal ID     | BYTE[7]  | uppercase letters + digits; null-padded, same convention |
| 36     | plate color     | BYTE     | JT/T 415-2006 §5.4.12; 0 = not yet plated |
| 37     | vehicle ID      | STRING   | VIN if plate_color==0, else the issued plate number (GBK, §4.2) |

**This body's `terminal ID` (offset 29, manufacturer-assigned, `BYTE[7]`) is a completely
different identifier from `InboundMessage.terminal_id`** (the header's `BCD[6]` terminal
phone, §4.4.3) — same English name in the spec's own vocabulary, two unrelated fields. Named
`manufacturer_terminal_id` here specifically to avoid that collision; every other module in
this codebase's `terminal_id` always means the header's phone-based identity.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.protocol.exceptions import MalformedFrameError
from src.protocol.strings import decode_gbk_string

_FIXED_BODY_LENGTH = 37  # everything up to and including plate_color


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
    manufacturer_id = body[4:9]
    terminal_model = _strip_null_padding(body[9:29])
    manufacturer_terminal_id = _strip_null_padding(body[29:36])
    plate_color = body[36]
    vehicle_identifier = decode_gbk_string(body[37:])

    return RegistrationRequest(
        province_id=province_id,
        city_county_id=city_county_id,
        manufacturer_id=manufacturer_id,
        terminal_model=terminal_model,
        manufacturer_terminal_id=manufacturer_terminal_id,
        plate_color=plate_color,
        vehicle_identifier=vehicle_identifier,
    )
