"""Batch position upload body parsing — JT/T 808-2013 §8.49 Table 76 ("定位数据批量上传数据
格式"), message ID `0x0704`:

| Offset | Field                | Type    | Notes |
|--------|----------------------|---------|-------|
| 0      | item count           | WORD    | number of location-report items, > 0 |
| 2      | position data type   | BYTE    | 0 = normal batch report ("正常位置批量汇报"), |
|        |                      |         | 1 = blind-zone supplement ("盲区补报") |
| 3      | items                | ...     | `item count` x Table 77, back-to-back |

Table 77 ("位置汇报数据项数据格式"), each item:

| Offset | Field                  | Type    | Notes |
|--------|------------------------|---------|-------|
| 0      | item body length (n)   | WORD    | |
| 2      | item body              | BYTE[n] | "定义见8.12 位置信息汇报" — identical format to `0x0200`'s |
|        |                        |         | body (`position_body.py`'s `parse_position_report_body`) |

**`is_backfill` is uniform across the whole message, not per-item.** JT808 Technical Design §8's
Handler table and §10 both describe `0x0704` as a single category — "ingest buffered positions
(backfill)" / "Backfill (`0x0704` / late `0x0200`): emitted with original `event_time` and
`is_backfill=true`" — with no carve-out for `position_data_type == 0`. This parser therefore
surfaces `position_data_type` on `BulkPositionReport` (so it is not silently discarded) but does
not use it to vary `is_backfill` per item; `bulk_location_handler.py` sets `is_backfill=True` for
every item in a `0x0704` message uniformly, following the Technical Design's documented
handler behavior rather than inventing a finer-grained split the approved design doc doesn't
draw. This is a judgment call on an underspecified point (documented here, not a blocking
conflict) — the primary spec's `position_data_type` distinguishes two *device-side* upload
triggers, but the platform-facing contract in the Technical Design collapses both into one
backfill classification.

Each item's own body is parsed via `position_body.parse_position_report_body` — a malformed or
truncated item raises `MalformedFrameError` exactly as a malformed `0x0200` body would,
propagating to the dispatcher's existing handler-error catch-all (Phase 9.4).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.handlers.position_body import PositionReportBody, parse_position_report_body
from src.protocol.exceptions import MalformedFrameError

_HEADER_LENGTH = 3  # item_count(2) + position_data_type(1)
_ITEM_LENGTH_PREFIX = 2  # each item's own WORD length prefix


@dataclass(frozen=True)
class BulkPositionReport:
    position_data_type: int
    items: list[PositionReportBody]


def parse_bulk_position_report(body: bytes) -> BulkPositionReport:
    if len(body) < _HEADER_LENGTH:
        raise MalformedFrameError(
            f"Bulk position report body shorter than the {_HEADER_LENGTH}-byte fixed header "
            f"({len(body)} bytes)."
        )

    item_count = int.from_bytes(body[0:2], "big")
    position_data_type = body[2]

    items: list[PositionReportBody] = []
    offset = _HEADER_LENGTH
    for index in range(item_count):
        if len(body) < offset + _ITEM_LENGTH_PREFIX:
            raise MalformedFrameError(
                f"Bulk position report truncated before item {index}'s length prefix."
            )
        item_length = int.from_bytes(body[offset : offset + 2], "big")
        offset += _ITEM_LENGTH_PREFIX
        if len(body) < offset + item_length:
            raise MalformedFrameError(
                f"Bulk position report truncated: item {index} declares {item_length} bytes "
                f"but only {len(body) - offset} remain."
            )
        item_body = body[offset : offset + item_length]
        items.append(parse_position_report_body(item_body))
        offset += item_length

    return BulkPositionReport(position_data_type=position_data_type, items=items)
