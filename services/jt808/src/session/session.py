"""Transport-layer connection session (Phase 9.1 — Transport Layer only).

**Deliberately narrower than the JT808 LLD's full "Session Manager" concept**
(`services/jt808/README.md`: "device_id -> vehicle_id, org_id, last_seen, auth_state") — at
this layer no frame has been parsed yet, so there is no `device_id` to key by and no
`auth_state` to hold (JT808 `0x0100`/`0x0102` registration/auth are message *handlers*,
explicitly out of this phase's scope). This is a pre-authentication, connection-scoped record:
one `ConnectionSession` per accepted TCP socket, identified by `connection_id`, not
`device_id`. A later phase's auth handler is expected to attach device identity onto (or
replace) this record once `0x0102` succeeds — not something this phase invents ahead of that
design.

`last_activity_at` is this phase's entire "heartbeat timeout infrastructure": it is touched on
*any* bytes received (`connection/connection.py`'s read loop), never on a specifically parsed
`0x0002` heartbeat message — that distinction (this framework only knows "bytes arrived", not
"a valid heartbeat arrived") is what keeps this phase protocol-agnostic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class SessionState(str, Enum):
    CONNECTED = "connected"
    CLOSED = "closed"


@dataclass
class ConnectionSession:
    connection_id: str
    remote_address: str
    connected_at: float = field(default_factory=time.monotonic)
    last_activity_at: float = field(default_factory=time.monotonic)
    state: SessionState = SessionState.CONNECTED

    def touch(self) -> None:
        self.last_activity_at = time.monotonic()

    def mark_closed(self) -> None:
        self.state = SessionState.CLOSED
