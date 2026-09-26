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

_BASIC_BLOCK_LENGTH = 28
ITEM_VIDEO_SIGNAL_LOSS = 0x15
ITEM_VIDEO_SIGNAL_OCCLUSION = 0x16


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
