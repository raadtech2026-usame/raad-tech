"""Shared `BCD[6]` `YY-MM-DD-hh-mm-ss` datetime codec (§4.2's packed-BCD convention, GMT+8 —
"本标准中之后涉及的时间均采用此时区", every timestamp in the standard is Beijing time). Every
message this deployable parses or builds with a `BCD[6]` time field uses this pair — originally
private to `handlers/position_body.py` (decode-only, `0x0200` always carries a real timestamp);
promoted here once the JT/T 1078 video-signaling bodies (`commands/video_signaling.py`) needed
both directions plus the "all-zero bytes means no time constraint" convention `0x9205`/`0x9201`
each declare for their own optional start/end time fields (spec §6.3.1/§6.3.3) — a convention
`0x0200` itself has no use for, so it stays out of the strict codec pair below and lives in
`decode_bcd_datetime_or_none`/`encode_bcd_datetime_or_none` instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.vendors.jt808.protocol.exceptions import MalformedFrameError

_DEVICE_TIMEZONE = timezone(timedelta(hours=8))  # GMT+8, §4.2's own stated convention
_BCD_DATETIME_BYTES = 6


def decode_bcd_datetime(data: bytes) -> datetime:
    """`BCD[6]` -> `YYMMDDHHMMSS` (device-local GMT+8) -> UTC `datetime`."""
    digits = []
    for byte in data:
        high, low = (byte >> 4) & 0x0F, byte & 0x0F
        if high > 9 or low > 9:
            raise MalformedFrameError(f"Invalid BCD nibble in datetime byte 0x{byte:02x}.")
        digits.append(high)
        digits.append(low)
    year = 2000 + digits[0] * 10 + digits[1]
    month = digits[2] * 10 + digits[3]
    day = digits[4] * 10 + digits[5]
    hour = digits[6] * 10 + digits[7]
    minute = digits[8] * 10 + digits[9]
    second = digits[10] * 10 + digits[11]
    try:
        local = datetime(year, month, day, hour, minute, second, tzinfo=_DEVICE_TIMEZONE)
    except ValueError as exc:
        raise MalformedFrameError(f"Invalid BCD datetime: {exc}") from exc
    return local.astimezone(timezone.utc)


def encode_bcd_datetime(value: datetime) -> bytes:
    """UTC `datetime` -> device-local GMT+8 -> `BCD[6]` (the encode-side mirror of
    `decode_bcd_datetime`, needed for every platform-initiated command carrying a time field —
    `0x9205`/`0x9201`/`0x9202`)."""
    local = value.astimezone(_DEVICE_TIMEZONE)
    digits = [
        local.year % 100,
        local.month,
        local.day,
        local.hour,
        local.minute,
        local.second,
    ]
    result = bytearray()
    for digit in digits:
        if not 0 <= digit <= 99:
            raise MalformedFrameError(f"BCD datetime component out of range: {digit}.")
        result.append(((digit // 10) << 4) | (digit % 10))
    return bytes(result)


def decode_bcd_datetime_or_none(data: bytes) -> datetime | None:
    """`0x9205`/`0x9201`'s own documented convention: all-zero `BCD[6]` bytes mean "no time
    constraint" (§6.3.1: "全部 0 表示无起始时间条件" / "全部 0 表示无终止时间条件") — this is a
    wire convention specific to those two messages' optional start/end time fields, not a general
    property of the `BCD[6]` type itself, so it is a separate function rather than a flag on
    `decode_bcd_datetime`."""
    if data == b"\x00" * _BCD_DATETIME_BYTES:
        return None
    return decode_bcd_datetime(data)


def encode_bcd_datetime_or_none(value: datetime | None) -> bytes:
    if value is None:
        return b"\x00" * _BCD_DATETIME_BYTES
    return encode_bcd_datetime(value)
