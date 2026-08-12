"""JT1078 relay broker configuration (ADR-0024 §8/§9). A distinct, independently-configured env
var (`JT1078_RELAY_BROKER_URL`, not `DEVICE_GATEWAY_BROKER_URL` or the Business API's own
`RAAD_BROKER__URL`) — this deployable's own manifest/config stays independent of every other
deployable's, even though an MVP deployment will typically point all three at the same Redis
instance (ADR-0008's own precedent, already applied identically for `DeviceGateway`). Left
unconfigured, the relay falls back to a logging-only session-event publisher and an in-memory
(never-persisted, single-process-only) viewer-token single-use registry — the same "fail loudly,
don't fake it" policy every other pending-infra port in this codebase already follows; it does
not silently pretend Redis-backed cross-process guarantees it cannot actually provide.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerConfig:
    url: str | None = None

    @classmethod
    def from_env(cls) -> "BrokerConfig":
        return cls(url=os.environ.get("JT1078_RELAY_BROKER_URL") or None)
