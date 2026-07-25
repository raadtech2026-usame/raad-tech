"""`LatestPositionWriter` — the port every vendor adapter's position handler uses to update the
"live" position snapshot, alongside (not instead of) publishing `DevicePositionReported` via
`EventPublisher` (`events/publisher_port.py`). Closes `docs/architecture/
post-f7-production-readiness-roadmap.md`'s Phase A item A2: `vehicle:{id}:last` — the Redis key
`backend/raad/modules/tracking/infra/adapters.RedisLatestPositionPort.get_latest` reads, and
`GET /tracking/vehicles/{id}/latest` ultimately depends on — had no writer anywhere in either
deployable before this.

**Ownership, per JT808 Technical Design §21.2's own sequence diagram** (`J->>R: SET
vehicle:{id}:last` before `J->>B: device.position_reported`), already cited by that Redis port's
own docstring as *this* deployable's job, not the Business API's: the device-plane service writes
the live snapshot directly, since it is the only component that sees every accepted position report
the instant it arrives, without waiting on broker delivery + consumer processing latency.

**Vendor-agnostic by construction**, mirroring `EventPublisher`'s own precedent exactly: this port
takes a `DevicePositionReported` (the same event every vendor adapter already constructs to
publish), so a new vendor adapter needs zero new code here — only to call `write()` next to its
existing `publish()` call, the same one-line addition this phase makes to `vendors/lsz/handlers/
position_handler.py`.

`LoggingLatestPositionWriter` is the default until a real broker is configured — degrades to a
structured log line, never an exception, mirroring `LoggingEventPublisher`'s identical "log for
now, not a security/correctness gap" stance (this is a cache write, not a durable record; the
`vehicle_positions` history row and the `DevicePositionReported` publish are unaffected either way).

**`RedisLatestPositionWriter`** (`redis_latest_position_writer.py`) is the real, Redis-backed
implementation — see that module's own docstring for the exact wire-payload contract, which must
stay byte-exact with `RedisLatestPositionPort.get_latest`'s parser on the Business API side (two
separate deployables, no shared Python code, no compiler to catch a mismatch — the same risk
`redis_event_publisher.py`'s own docstring already flags for the broader event envelope).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.events.device_position_reported import DevicePositionReported
from src.logging_setup import get_logger, log_with_fields

logger = get_logger("device_gateway.latest_position.writer")


class LatestPositionWriter(ABC):
    @abstractmethod
    async def write(self, event: DevicePositionReported) -> None:
        raise NotImplementedError


class LoggingLatestPositionWriter(LatestPositionWriter):
    """Default binding until a real broker is configured — see module docstring."""

    async def write(self, event: DevicePositionReported) -> None:
        log_with_fields(
            logger,
            10,
            "latest_position_snapshot_not_persisted_no_redis_configured",
            vehicle_id=event.vehicle_id,
        )
