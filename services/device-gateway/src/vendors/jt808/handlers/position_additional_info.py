"""`0x0200` additional-information items (supplier spec `mdvrdocs/MDVR-808-1078-spec.pdf` Table
5.11, "位置附加信息项列表"): a sequence of `ID (BYTE) | length (BYTE) | value` items after the
28-byte basic block.

Only the two JT/T 1078 video items are interpreted here (ADR-0046 §1):

- `0x15` 视频信号丢失报警状态 — DWORD, bit *n-1* set when logical channel *n* has lost its video
  signal;
- `0x16` 视频信号遮挡报警状态 — DWORD, same layout, channel occluded.

The terminal reports `0x15` on every position report. Captured from terminal
`00000000014482607571` on 2026-09-19: `0x15 = 0x0000000A` (ch2 and ch4 lost, ch1 and ch3 with
signal), which is exactly its physical installation - cameras on ch1 and ch3 only. This is the
authoritative "is there a camera on this channel" signal; RAAD never infers it from the channel
count the terminal reports in `0x1003`.

A malformed or truncated item list stops the walk: the items before it are still returned, and the
position itself is never rejected because of an additional item.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.vendors.jt808.protocol.bcd_datetime import decode_bcd_datetime

_BASIC_BLOCK_LENGTH = 28
ITEM_VIDEO_SIGNAL_LOSS = 0x15
ITEM_VIDEO_SIGNAL_OCCLUSION = 0x16
ITEM_ADAS_ALARM = 0x64
ITEM_DSM_ALARM = 0x65

#: Su-biao T/JSATL12 ADAS alarm types (Item 0x64, Table 4-13).
ADAS_ALARM_TYPES: dict[int, str] = {
    0x01: "forward_collision",     # 前向碰撞报警 (FCW)
    0x02: "lane_departure",        # 车道偏离报警 (LDW)
    0x03: "headway",               # 车距过近报警 (HMW)
    0x04: "pedestrian_collision",  # 行人碰撞报警 (PCW)
    0x05: "frequent_lane_change",  # 频繁变道报警
    0x06: "road_sign_overrun",     # 道路标识超限报警
    0x07: "obstacle_warning",      # 障碍物报警
}

#: Su-biao T/JSATL12 DSM driver behavior alarm types (Item 0x65).
DSM_ALARM_TYPES: dict[int, str] = {
    0x01: "fatigue",          # 疲劳驾驶报警
    0x02: "phone_call",       # 接打电话报警
    0x03: "smoking",          # 抽烟报警
    0x04: "distraction",      # 分神驾驶报警
    0x05: "driver_absent",    # 驾驶员异常报警 / 脱岗
}


def parse_additional_items(body: bytes) -> dict[int, bytes]:
    items: dict[int, bytes] = {}
    i = _BASIC_BLOCK_LENGTH
    while i + 2 <= len(body):
        item_id = body[i]
        length = body[i + 1]
        value = body[i + 2 : i + 2 + length]
        if len(value) != length:
            break
        items[item_id] = value
        i += 2 + length
    return items


@dataclass(frozen=True)
class VideoSignalStatus:
    #: Bit n-1 set = logical channel n has no video signal.
    loss_mask: int
    #: Bit n-1 set = logical channel n is occluded; `None` when the terminal did not report it.
    occlusion_mask: int | None


@dataclass(frozen=True)
class AdasAlarmInfo:
    alarm_id: int
    flag_status: int  # 0: start, 1: repeat, 2: end
    alarm_type: str
    raw_alarm_type: int
    alarm_level: int  # 1: warning, 2: critical
    front_vehicle_speed: int  # km/h
    front_vehicle_distance: float  # meters (from 1/10 m byte)
    deviation_type: int  # 1: left, 2: right
    vehicle_speed: int  # km/h
    altitude: int  # meters
    latitude: float | None
    longitude: float | None
    event_time: datetime | None


def _dword(value: bytes | None) -> int | None:
    if value is None or len(value) != 4:
        return None
    return int.from_bytes(value, "big")


def video_signal_status(items: dict[int, bytes]) -> VideoSignalStatus | None:
    """`None` when the report carries no `0x15` item: absence of evidence is not evidence of a
    camera, so nothing is published and the channel stays "unknown" downstream."""
    loss = _dword(items.get(ITEM_VIDEO_SIGNAL_LOSS))
    if loss is None:
        return None
    return VideoSignalStatus(
        loss_mask=loss, occlusion_mask=_dword(items.get(ITEM_VIDEO_SIGNAL_OCCLUSION))
    )


def adas_alarm_info(items: dict[int, bytes]) -> AdasAlarmInfo | None:
    """Parses Su-biao T/JSATL12 Active Safety ADAS alarm item `0x64`.

    Returns `None` if the item is absent or shorter than the standard 31 bytes.
    """
    value = items.get(ITEM_ADAS_ALARM)
    if value is None or len(value) < 31:
        return None

    alarm_id = int.from_bytes(value[0:4], "big")
    flag_status = value[4]
    raw_type = value[5]
    alarm_type = ADAS_ALARM_TYPES.get(raw_type, f"adas_unknown_{raw_type}")
    alarm_level = value[6]
    front_speed = value[7]
    front_distance = value[8] / 10.0
    deviation_type = value[9]
    vehicle_speed = value[12]
    altitude = int.from_bytes(value[13:15], "big")
    lat_raw = int.from_bytes(value[15:19], "big")
    lng_raw = int.from_bytes(value[19:23], "big")
    latitude = lat_raw / 1_000_000.0 if lat_raw != 0 else None
    longitude = lng_raw / 1_000_000.0 if lng_raw != 0 else None

    event_time: datetime | None = None
    try:
        event_time = decode_bcd_datetime(value[23:29])
    except Exception:
        event_time = None

    return AdasAlarmInfo(
        alarm_id=alarm_id,
        flag_status=flag_status,
        alarm_type=alarm_type,
        raw_alarm_type=raw_type,
        alarm_level=alarm_level,
        front_vehicle_speed=front_speed,
        front_vehicle_distance=front_distance,
        deviation_type=deviation_type,
        vehicle_speed=vehicle_speed,
        altitude=altitude,
        latitude=latitude,
        longitude=longitude,
        event_time=event_time,
    )
