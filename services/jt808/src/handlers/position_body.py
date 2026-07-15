"""Position report basic-info parsing — JT/T 808-2013 §8.18 Table 23 ("位置基本信息数据格式"),
shared verbatim by `0x0200` (whose whole body *is* this structure, plus an optional trailing
additional-info item list) and by each item inside `0x0704`'s batch (§8.49 Table 77: "位置汇报
数据体" = "定义见8.12 位置信息汇报" — literally "defined by [the same as] 8.12/8.18 Location
Report").

Fixed 28-byte layout, big-endian (§4.3), Table 23 verbatim:

| Offset | Field       | Type    | Notes |
|--------|-------------|---------|-------|
| 0      | alarm flag  | DWORD   | bit definitions Table 24 — opaque bitfield, not decoded here |
| 4      | status      | DWORD   | bit definitions Table 25 — decoded only for the two bits this |
|        |             |         | parser needs: bit 2 (0=N/1=S), bit 3 (0=E/1=W) |
| 8      | latitude    | DWORD   | degrees * 10^6, unsigned magnitude (sign from status bit 2) |
| 12     | longitude   | DWORD   | degrees * 10^6, unsigned magnitude (sign from status bit 3) |
| 16     | altitude    | WORD    | meters |
| 18     | speed       | WORD    | 1/10 km/h |
| 20     | direction   | WORD    | 0-359, 0 = north, clockwise |
| 22     | time        | BCD[6]  | YY-MM-DD-hh-mm-ss, GMT+8 (§4.2's own note: "本标准中之后涉及的 |
|        |             |         | 时间均采用此时区" — every timestamp in this standard is GMT+8) |

Total fixed length: 4+4+4+4+2+2+2+6 = 28 bytes. A real body may carry a trailing "位置附加信息
项列表" (additional-info item list, Table 26) after these 28 bytes — variable-length,
ID+length+value encoded. This parser only extracts the fixed portion; the additional-info list
is neither decoded nor validated (JT808 Technical Design §10's canonical `PositionReport` shape
has no field any additional-info item would fill — altitude itself is parsed here for
structural completeness but is *not* part of that canonical shape either, since no approved
document defines a Tracking-side altitude concept yet, `tracking/domain/value_objects.py`'s own
module docstring). Trailing bytes past offset 28 are simply ignored, not an error.

**Sign convention:** latitude/longitude arrive as unsigned magnitudes; status bits 2/3 (Table
25) carry the hemisphere. `status bit 2 == 1` means south latitude (negate); `bit 3 == 1` means
west longitude (negate) — applied here so this parser's output is already signed-degree
`float`, matching Tracking's `GeoPoint(latitude, longitude)` convention (lat +/-90, lng +/-180)
one-to-one, even though this module never imports or constructs that type itself (`handlers/
__init__.py`'s architecture boundary — see `location_handler.py`'s module docstring).

**Speed conversion:** the wire unit is 1/10 km/h; the canonical `PositionReport`/Tracking's
`SpeedKph` are whole km/h (`SMALLINT`, Database Design). No approved document specifies a
rounding mode for this narrowing conversion — `round()` (nearest, ties-to-even) is used as the
most accurate choice available; this is a data-type precision decision, not a business rule.

**Time conversion:** the BCD[6] field decodes to a naive `YYMMDDHHMMSS` reading in GMT+8 (the
spec's own stated timezone for every timestamp in the standard); this parser immediately
converts it to a timezone-aware UTC `datetime`, since every `_at`/`event_time` field elsewhere
in this codebase is UTC (`.claude/rules/naming.md`: "Timestamps: `_at` suffix, UTC") and
downstream consumers (Tracking) never see or reason about GMT+8.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.protocol.exceptions import MalformedFrameError

_FIXED_BODY_LENGTH = 28

_STATUS_BIT_SOUTH_LATITUDE = 0b0100  # bit 2
_STATUS_BIT_WEST_LONGITUDE = 0b1000  # bit 3

_DEVICE_TIMEZONE = timezone(timedelta(hours=8))  # GMT+8, §4.2's own stated convention


@dataclass(frozen=True)
class PositionReportBody:
    alarm_flags: int
    status: int
    latitude: float
    longitude: float
    altitude_m: int
    speed_kph: int
    heading_deg: int
    event_time: datetime  # UTC


def _decode_bcd_datetime(data: bytes) -> datetime:
    """BCD[6] -> `YYMMDDHHMMSS` (device-local GMT+8) -> UTC `datetime` (§4.2's packed-BCD
    convention, same nibble decoding `header.py`'s `_decode_bcd_phone` uses for the terminal
    phone, applied here to a date/time field instead)."""
    digits = []
    for byte in data:
        high, low = (byte >> 4) & 0x0F, byte & 0x0F
        if high > 9 or low > 9:
            raise MalformedFrameError(
                f"Invalid BCD nibble in position time byte 0x{byte:02x}."
            )
        digits.append(high)
        digits.append(low)
    year = 2000 + digits[0] * 10 + digits[1]
    month = digits[2] * 10 + digits[3]
    day = digits[4] * 10 + digits[5]
    hour = digits[6] * 10 + digits[7]
    minute = digits[8] * 10 + digits[9]
    second = digits[10] * 10 + digits[11]
    try:
        local = datetime(
            year, month, day, hour, minute, second, tzinfo=_DEVICE_TIMEZONE
        )
    except ValueError as exc:
        raise MalformedFrameError(f"Invalid position report timestamp: {exc}") from exc
    return local.astimezone(timezone.utc)


def parse_position_report_body(body: bytes) -> PositionReportBody:
    if len(body) < _FIXED_BODY_LENGTH:
        raise MalformedFrameError(
            f"Position report body shorter than the {_FIXED_BODY_LENGTH}-byte fixed portion "
            f"({len(body)} bytes)."
        )

    alarm_flags = int.from_bytes(body[0:4], "big")
    status = int.from_bytes(body[4:8], "big")
    raw_latitude = int.from_bytes(body[8:12], "big")
    raw_longitude = int.from_bytes(body[12:16], "big")
    altitude_m = int.from_bytes(body[16:18], "big")
    raw_speed = int.from_bytes(body[18:20], "big")
    heading_deg = int.from_bytes(body[20:22], "big")
    event_time = _decode_bcd_datetime(body[22:28])

    latitude = raw_latitude / 1_000_000
    if status & _STATUS_BIT_SOUTH_LATITUDE:
        latitude = -latitude
    longitude = raw_longitude / 1_000_000
    if status & _STATUS_BIT_WEST_LONGITUDE:
        longitude = -longitude

    return PositionReportBody(
        alarm_flags=alarm_flags,
        status=status,
        latitude=latitude,
        longitude=longitude,
        altitude_m=altitude_m,
        speed_kph=round(raw_speed / 10),
        heading_deg=heading_deg,
        event_time=event_time,
    )
