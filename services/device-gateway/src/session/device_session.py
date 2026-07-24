"""DeviceSession — the higher-level, terminal-identity-keyed session (Phase 9.2; Phase 3.4 §5;
Phase 2 §21.1). Distinct from `session.py`'s `ConnectionSession` (Phase 9.1, transport-level,
keyed by `connection_id`): a `DeviceSession` only exists once a connection has been
authenticated, keyed by `terminal_id` — the JT/T 808 device identity, not the socket.

**States implemented — deliberately only three, not the full connectivity diagram.** Phase 3.4
§3 / Phase 2 §21.1 draw `Registered`/`Idle`/`Backfilling` as additional states, but:
- `Registered` precedes authentication (`0x0100` only) — this phase's `DeviceSession` is
  created *after* authentication (`DeviceSessionManager.create`'s own docstring), so there is
  nothing for this class to represent before that point; `Registered` belongs to a future
  `RegisterHandler`'s bookkeeping, not this session object.
- `Idle` is a GPS-cadence distinction ("reduced cadence when stationary," Phase 2 §21.1) that
  requires interpreting location reports — explicitly out of this phase's scope (no GPS
  position processing). Modeling it here without the ability to ever detect it would be
  inventing dead state.
- `Backfilling` requires ingesting `0x0704` bulk-location messages — packet parsing, also out
  of scope.

So this phase models exactly the states it can genuinely drive from transport-layer signals
alone: `AUTHENTICATED` (just created, per `.claude/rules/workflow.md` #8's resolved reading —
see `device_session_manager.py`'s module docstring for the Phase 3.4 §21.1-vs-§3 conflict this
was resolved against), `ONLINE` (promoted on the first `touch()`), and `OFFLINE` (terminal —
the session is about to be removed from the registry). Adding `IDLE`/`BACKFILLING`/`REGISTERED`
is a later phase's job, once the packet parser/handlers that could actually drive those
transitions exist.

`device_id`/`vehicle_id`/`organization_id` mirror Phase 3.4 §5's `resolve()` contract shape
exactly (`{device_id, vehicle_id, organization_id, node_id, auth_state, last_seen}`) minus
`node_id` (cross-shard command routing — no multi-node deployment concept exists at this
phase, not requested in scope) and `auth_state` (redundant with `state` here, since this
object's mere existence already means "authenticated"). **This phase never resolves these
three fields itself** — `.claude/rules/architecture.md`: "SessionManager must never call
business modules." They are optional, caller-supplied pass-through data: a future
`AuthHandler` (not built yet) will have resolved `terminal_id -> device/vehicle/org` via the
Business API's provisioning read-model (Phase 3.4 §15) *before* calling
`DeviceSessionManager.create(...)`, and hands the already-resolved values through.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class DeviceConnectivityState(str, Enum):
    """Phase 2 §21.1's connectivity terminology — the runtime dimension, orthogonal to
    `fleet_device`'s business `DeviceLifecycleState` (Phase 7.1: registered/activated/
    assigned/suspended/retired). Never merge the two: Phase 2 §19.3 states plainly a device
    can be `Assigned` (business) and `Offline` (connectivity) simultaneously."""

    AUTHENTICATED = "authenticated"
    ONLINE = "online"
    OFFLINE = "offline"


@dataclass
class DeviceSession:
    terminal_id: str
    connection_id: str
    device_id: str | None = None
    vehicle_id: str | None = None
    organization_id: str | None = None
    authenticated_at: float = field(default_factory=time.monotonic)
    last_seen_at: float = field(default_factory=time.monotonic)
    state: DeviceConnectivityState = DeviceConnectivityState.AUTHENTICATED

    def touch(self) -> None:
        self.last_seen_at = time.monotonic()

    def mark_online(self) -> None:
        self.state = DeviceConnectivityState.ONLINE

    def mark_offline(self) -> None:
        self.state = DeviceConnectivityState.OFFLINE
