"""`DeviceResourceListReported` — published by `handlers/resource_list_handler.py` when a
terminal replies to a `QUERY_RESOURCE_LIST` (`0x9205`) command with its own `0x1205` resource
list report (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.3.2 Table 6.8/6.9). Lets the Business API's
eventual playback-browsing flow (ADR-0024 §7 point 2: "let the operator browse what recordings
actually exist on the device before requesting playback") learn what the MDVR's own local
storage actually holds, without ever fetching or storing a byte of the recordings themselves —
this event carries only the resource *catalog* (channel/time-window/type/size per item), never
media.

**`items` is a plain list of dicts, not a list of a shared dataclass**, matching every other
event in this deployable that carries a variable-length item list — there is no precedent
elsewhere in `src/events/` for a nested-dataclass event payload, and `redis_event_publisher.py`'s
`_envelope` already JSON-serializes the whole payload dict directly, so a list of dicts survives
that round trip with zero extra serialization code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DeviceResourceListReported:
    terminal_id: str
    organization_id: str | None
    vehicle_id: str | None
    device_id: str | None
    correlation_id: str
    total_resource_count: int
    items: tuple[dict[str, Any], ...]
    event_time: datetime
    received_at: datetime
