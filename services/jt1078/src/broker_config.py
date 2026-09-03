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
    #: **Default 0 = trimming DISABLED. Do not turn this on without first making the device
    #: registry durable.** Live-proven regression, 2026-09-02: this was briefly defaulted to
    #: 100_000 to bound Redis memory, and trimming immediately evicted the oldest entries —
    #: which included the `DeviceRegistered`/`DeviceActivated`/`DeviceAssignedToVehicle` events
    #: from 2026-08-18 that `services/device-gateway`'s `DeviceRegistryProjection` rebuilds
    #: itself from on every cold start (`RedisDeviceRegistryConsumer.replay_from_start`, a full
    #: `XRANGE` over the whole stream). The projection came back empty and the physical MDVR
    #: could no longer authenticate at all (`authentication_failed` on every `0x0102`).
    #: `raad:events` is therefore not a transient bus: for the device registry it is the durable
    #: log of record, with unbounded retention. Any finite cap eventually evicts those founding
    #: events, because they are by definition the oldest and position reports are high-volume —
    #: so no "safe" non-zero value exists under the current design. Bounding Redis memory needs
    #: the projection to stop depending on infinite history (persist it, or compact registry
    #: events onto their own keys) — a design change, not a tuning knob.
    stream_max_length: int = 0

    @classmethod
    def from_env(cls) -> "BrokerConfig":
        return cls(
            url=os.environ.get("JT1078_RELAY_BROKER_URL") or None,
            stream_max_length=int(
                os.environ.get("JT1078_RELAY_STREAM_MAX_LENGTH", "0")
            ),
        )
