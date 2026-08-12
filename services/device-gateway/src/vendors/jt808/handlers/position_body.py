"""Position report basic-info parsing — confirmed byte-for-byte identical between the originally-
cited JT/T 808-2013 §8.18 Table 23 ("位置基本信息数据格式") and the confirmed JT/T 808-2019
supplier spec (`mdvrdocs/MDVR-808-1078-spec.pdf` §5.2.1 Table 5.7 "消息体结构" / Table 5.8
"位置信息汇报基本信息格式" — ADR-0025 §2's own "0x0200/AlarmFlags byte-level diff" item,
flagged as outstanding verification work in that ADR's "What this ADR does not do," now
resolved: **no field, offset, width, or byte order differs between the two editions for this
message** — the implementation below was already correct and needed no code change, only this
citation update). Shared verbatim by `0x0200` (whose whole body *is* this structure, plus an
optional trailing additional-info item list, Table 5.11) and by each item inside `0x0704`'s
batch (identical basic-info structure per the batch item format).

Fixed 28-byte layout, big-endian (§4.3), Table 5.8 verbatim (offsets/types cross-checked 1:1
against the original Table 23 citation below — unchanged):

| Offset | Field       | Type    | Notes |
|--------|-------------|---------|-------|
| 0      | alarm flag  | DWORD   | bit definitions Table 24 / Table 5.10 (32 bits, cross-checked |
|        |             |         | 1:1 against the supplier spec — identical) — opaque bitfield, |
|        |             |         | not decoded here |
| 4      | status      | DWORD   | bit definitions Table 25 / Table 5.9 — decoded only for the |
|        |             |         | two bits this parser needs: bit 2 (0=N/1=S), bit 3 (0=E/1=W) |
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
from datetime import datetime

from src.vendors.jt808.protocol.bcd_datetime import decode_bcd_datetime
from src.vendors.jt808.protocol.exceptions import MalformedFrameError

_FIXED_BODY_LENGTH = 28

_STATUS_BIT_SOUTH_LATITUDE = 0b0100  # bit 2
_STATUS_BIT_WEST_LONGITUDE = 0b1000  # bit 3


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
    event_time = decode_bcd_datetime(body[22:28])

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
