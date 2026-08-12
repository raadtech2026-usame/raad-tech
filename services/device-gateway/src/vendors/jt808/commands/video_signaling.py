"""JT/T 1078 video-signaling message bodies (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.2/§6.3,
ADR-0024 §1/§6/§7/§8, ADR-0025 §5) — the JT1078 device-plane signaling forwarding phase.

**Wire-encoding ownership, a deliberate refinement of ADR-0024 §8's literal wording:** that ADR
describes the Business API publishing a command event carrying "its already-encoded body." This
module instead owns the actual byte-level encoding, on the device-gateway side, for the same
reason every other message body in this deployable (`registration_body.py`,
`authentication_body.py`, `position_body.py`) is encoded/decoded here and nowhere else: keeping
*all* JT/T 808/1078 wire-format knowledge inside the device-plane deployable is exactly the
Anti-Corruption-Layer principle ADR-0009 established and ADR-0025 confirms is still in force —
the Business API (business plane) should never need to know a JT1078 body's byte layout to
request a video session, only the *business-meaningful* fields (channel, stream type, playback
window, the relay's own ingest coordinates). The event device-gateway's `commands/
redis_video_signaling_consumer.py` consumes therefore carries structured fields, not raw bytes;
this module is what turns those fields into the exact wire body ADR-0024 §8 describes forwarding
"as-is... no opcode translation" once encoded.

Six platform -> terminal (downlink) message bodies, one terminal -> platform (uplink) body:

| Message | Direction | Spec table | Dataclass |
|---|---|---|---|
| `0x9101` live video request | down | Table 6.2 | `LiveVideoRequest` |
| `0x9102` live video control | down | Table 6.4 | `LiveVideoControl` |
| `0x9105` live status notify (packet-loss %) | down | Table 6.5 | `LiveVideoStatusNotify` |
| `0x9205` query resource list | down | Table 6.7 | `QueryResourceList` |
| `0x9201` playback request | down | Table 6.10 | `PlaybackRequest` |
| `0x9202` playback control | down | Table 6.11 | `PlaybackControl` |
| `0x1205` resource list report | up | Table 6.8/6.9 | `ResourceListReport` |

**Server IP address (`0x9101`/`0x9201`)** is a length-prefixed `STRING` (`BYTE` length `n` +
`n` bytes GBK-encoded, mirroring `authentication_body.py`'s identical length-prefix-then-STRING
shape) — an ASCII IPv4/hostname round-trips through GBK unchanged (GBK is ASCII-compatible for
the codepoints an IP/hostname ever uses), so `protocol/strings.py`'s existing codec is reused
rather than a second one written for what is, byte-for-byte, the same wire type.

**Alarm-flag filter (`0x9205`'s own `报警标志` field, Table 6.7) is `64BITS` (8 bytes): bits
0-31 are `0x0200`'s own `Table 5.10` alarm bits (see `handlers/position_body.py`), bits 32-63
are Table 5.18 (I/O alarm bits) — this module treats the whole 8 bytes as an opaque filter value
passed through verbatim (an `int`), exactly the same "opaque bitfield, not decoded here"
discipline `position_body.py` already applies to the 32-bit version, for the identical reason:
no approved document needs any individual bit named yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.vendors.jt808.protocol.bcd_datetime import (
    decode_bcd_datetime,
    encode_bcd_datetime,
    encode_bcd_datetime_or_none,
)
from src.vendors.jt808.protocol.exceptions import MalformedFrameError
from src.vendors.jt808.protocol.strings import decode_gbk_string, encode_gbk_string

_ALARM_FLAG_FILTER_BYTES = 8
_RESOURCE_ITEM_LENGTH = 28  # Table 6.9's fixed per-item length


def _encode_length_prefixed_ip(ip_address: str) -> bytes:
    encoded = encode_gbk_string(ip_address)
    if len(encoded) > 0xFF:
        raise MalformedFrameError(
            f"Server IP address too long to length-prefix in one BYTE: {ip_address!r}."
        )
    return bytes([len(encoded)]) + encoded


# --- 0x9101 live video request (downlink, Table 6.2) --------------------------------------


@dataclass(frozen=True)
class LiveVideoRequest:
    server_ip: str
    tcp_port: int
    udp_port: int
    logical_channel: int
    data_type: int  # 0 A/V, 1 video, 2 two-way intercom, 3 listen-only, 4 broadcast, 5 passthrough
    stream_type: int  # 0 main, 1 sub


def encode_live_video_request(request: LiveVideoRequest) -> bytes:
    return (
        _encode_length_prefixed_ip(request.server_ip)
        + request.tcp_port.to_bytes(2, "big")
        + request.udp_port.to_bytes(2, "big")
        + bytes([request.logical_channel, request.data_type, request.stream_type])
    )


# --- 0x9102 live video control (downlink, Table 6.4) ---------------------------------------


@dataclass(frozen=True)
class LiveVideoControl:
    logical_channel: int
    control: int  # 0 close, 1 switch stream, 2 pause, 3 resume, 4 close intercom
    close_av_type: int = 0  # 0 close both, 1 close audio only, 2 close video only
    switch_stream_type: int = 0  # 0 main, 1 sub


def encode_live_video_control(control: LiveVideoControl) -> bytes:
    return bytes(
        [
            control.logical_channel,
            control.control,
            control.close_av_type,
            control.switch_stream_type,
        ]
    )


# --- 0x9105 live status notify (downlink, Table 6.5) ----------------------------------------


@dataclass(frozen=True)
class LiveVideoStatusNotify:
    logical_channel: int
    packet_loss_rate_percent: int  # already "rate * 100, integer part" per the spec's own wording


def encode_live_video_status_notify(notify: LiveVideoStatusNotify) -> bytes:
    return bytes([notify.logical_channel, notify.packet_loss_rate_percent])


# --- 0x9205 query resource list (downlink, Table 6.7) ---------------------------------------


@dataclass(frozen=True)
class QueryResourceList:
    logical_channel: int  # 0 = all channels
    start_time: datetime | None  # UTC; None = no start-time constraint
    end_time: datetime | None  # UTC; None = no end-time constraint
    alarm_flag_filter: int  # 64-bit opaque filter, 0 = no alarm filter
    resource_type: int  # 0 A/V, 1 audio, 2 video, 3 video-or-A/V
    stream_type: int  # 0 all, 1 main, 2 sub
    storage_type: int  # 0 all, 1 main storage, 2 disaster-backup storage


def encode_query_resource_list(query: QueryResourceList) -> bytes:
    return (
        bytes([query.logical_channel])
        + encode_bcd_datetime_or_none(query.start_time)
        + encode_bcd_datetime_or_none(query.end_time)
        + query.alarm_flag_filter.to_bytes(_ALARM_FLAG_FILTER_BYTES, "big")
        + bytes([query.resource_type, query.stream_type, query.storage_type])
    )


# --- 0x9201 playback request (downlink, Table 6.10) ------------------------------------------


@dataclass(frozen=True)
class PlaybackRequest:
    server_ip: str
    tcp_port: int  # 0 if not using TCP
    udp_port: int  # 0 if not using UDP
    logical_channel: int
    av_type: int  # 0 A/V, 1 audio, 2 video
    stream_type: int  # 0 main, 1 sub
    storage_type: int  # 0 main-or-backup, 1 main, 2 backup
    playback_mode: int  # 0 normal, 1 FF, 2 keyframe reverse, 3 keyframe-only, 4 single-frame upload
    speed_multiplier: int  # valid only when playback_mode in (1, 2); 0 invalid,1..5 -> 1/2/4/8/16x
    start_time: datetime  # UTC; when playback_mode == 4, this is the frame-upload time
    end_time: datetime  # UTC; ignored by the spec when playback_mode == 4


def encode_playback_request(request: PlaybackRequest) -> bytes:
    return (
        _encode_length_prefixed_ip(request.server_ip)
        + request.tcp_port.to_bytes(2, "big")
        + request.udp_port.to_bytes(2, "big")
        + bytes(
            [
                request.logical_channel,
                request.av_type,
                request.stream_type,
                request.storage_type,
                request.playback_mode,
                request.speed_multiplier,
            ]
        )
        + encode_bcd_datetime(request.start_time)
        + encode_bcd_datetime(request.end_time)
    )


# --- 0x9202 playback control (downlink, Table 6.11) ------------------------------------------


@dataclass(frozen=True)
class PlaybackControl:
    av_channel: int
    control: int  # 0 start,1 pause,2 stop,3 FF,4 keyframe reverse,5 seek,6 keyframe-only
    speed_multiplier: int = 0  # valid only when control in (3, 4); 0 invalid,1..5 -> 1/2/4/8/16x
    seek_position: datetime | None = None  # UTC; valid only when control == 5


def encode_playback_control(control: PlaybackControl) -> bytes:
    return (
        bytes([control.av_channel, control.control, control.speed_multiplier])
        + encode_bcd_datetime_or_none(control.seek_position)
    )


# --- 0x1205 resource list report (uplink, Table 6.8/6.9) -------------------------------------


@dataclass(frozen=True)
class ResourceListItem:
    logical_channel: int
    start_time: datetime  # UTC
    end_time: datetime  # UTC
    alarm_flag: int  # 64-bit opaque, same convention as QueryResourceList.alarm_flag_filter
    resource_type: int  # 0 A/V, 1 audio, 2 video
    stream_type: int  # 0 main, 1 sub
    storage_type: int  # 0 main storage, 2 disaster-backup storage (Table 6.9's own value set)
    file_size_bytes: int


@dataclass(frozen=True)
class ResourceListReport:
    original_serial_no: int  # echoes the QUERY_RESOURCE_LIST request's own serial_no
    total_resource_count: int
    items: tuple[ResourceListItem, ...]


def _parse_resource_item(data: bytes) -> ResourceListItem:
    return ResourceListItem(
        logical_channel=data[0],
        start_time=decode_bcd_datetime(data[1:7]),
        end_time=decode_bcd_datetime(data[7:13]),
        alarm_flag=int.from_bytes(data[13:21], "big"),
        resource_type=data[21],
        stream_type=data[22],
        storage_type=data[23],
        file_size_bytes=int.from_bytes(data[24:28], "big"),
    )


def parse_resource_list_report(body: bytes) -> ResourceListReport:
    if len(body) < 6:
        raise MalformedFrameError(
            f"Resource list report body shorter than the 6-byte fixed header ({len(body)} bytes)."
        )
    original_serial_no = int.from_bytes(body[0:2], "big")
    total_resource_count = int.from_bytes(body[2:6], "big")

    items_bytes = body[6:]
    if len(items_bytes) % _RESOURCE_ITEM_LENGTH != 0:
        raise MalformedFrameError(
            "Resource list report item section is not a whole multiple of the "
            f"{_RESOURCE_ITEM_LENGTH}-byte item length ({len(items_bytes)} bytes)."
        )
    items = tuple(
        _parse_resource_item(items_bytes[offset : offset + _RESOURCE_ITEM_LENGTH])
        for offset in range(0, len(items_bytes), _RESOURCE_ITEM_LENGTH)
    )

    return ResourceListReport(
        original_serial_no=original_serial_no,
        total_resource_count=total_resource_count,
        items=items,
    )
