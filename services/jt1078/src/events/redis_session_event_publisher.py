"""`RedisSessionEventPublisher` — the real, broker-backed `SessionEventPublisher`. Publishes onto
the **same** shared `raad:events` Redis Stream (ADR-0008) `device-gateway`'s own publishers and
the Business API's outbox relay already use — the relay becomes a third participant on this
stream, exactly as ADR-0024 §9 requires ("no new broker capability, just a new named
participant"). Wire envelope deliberately byte-for-byte compatible with `backend/raad/core/events/
redis_streams.py` and `device-gateway/src/events/redis_event_publisher.py`'s own identical shape
— a single `data` field holding a JSON blob with `event_id`/`event_type`/`version`/`occurred_at`/
`org_id`/`correlation_id`/`payload`/`aggregate_type`/`aggregate_id`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from src.events.publisher_port import SessionEvent, SessionEventPublisher
from src.events.session_events import VideoSessionActivated, VideoSessionEnded, VideoSessionFailed

DEFAULT_STREAM_NAME = "raad:events"


def _envelope(
    *,
    event_type: str,
    org_id: str | None,
    aggregate_type: str,
    aggregate_id: str,
    occurred_at: datetime,
    payload: dict[str, Any],
    correlation_id: str | None,
) -> dict[str, str]:
    return {
        "data": json.dumps(
            {
                "event_id": str(uuid.uuid4()),
                "event_type": event_type,
                "version": 1,
                "occurred_at": occurred_at.isoformat(),
                "org_id": org_id,
                "correlation_id": correlation_id,
                "payload": payload,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
            }
        )
    }


def _fields_for(event: SessionEvent) -> dict[str, str]:
    common = {
        "session_id": event.session_id,
        "terminal_id": event.terminal_id,
        "organization_id": event.organization_id,
        "vehicle_id": event.vehicle_id,
        "device_id": event.device_id,
        "correlation_id": event.correlation_id,
    }
    if isinstance(event, VideoSessionActivated):
        return _envelope(
            event_type="VideoSessionActivated",
            org_id=event.organization_id,
            aggregate_type="VideoSession",
            aggregate_id=event.session_id,
            occurred_at=event.event_time,
            correlation_id=event.correlation_id,
            payload=common,
        )
    if isinstance(event, VideoSessionEnded):
        return _envelope(
            event_type="VideoSessionEnded",
            org_id=event.organization_id,
            aggregate_type="VideoSession",
            aggregate_id=event.session_id,
            occurred_at=event.event_time,
            correlation_id=event.correlation_id,
            payload={**common, "reason": event.reason},
        )
    if isinstance(event, VideoSessionFailed):
        return _envelope(
            event_type="VideoSessionFailed",
            org_id=event.organization_id,
            aggregate_type="VideoSession",
            aggregate_id=event.session_id,
            occurred_at=event.event_time,
            correlation_id=event.correlation_id,
            payload={**common, "reason": event.reason},
        )
    raise TypeError(f"Unrecognized session event type: {type(event)!r}")


class RedisSessionEventPublisher(SessionEventPublisher):
    def __init__(
        self,
        redis_client: Redis,
        *,
        stream_name: str = DEFAULT_STREAM_NAME,
        max_length: int = 0,
    ) -> None:
        self._redis = redis_client
        self._stream_name = stream_name
        #: Approximate `raad:events` cap, applied per `XADD` (2026-09-02). Must match the other
        #: publishers writing to this same stream (`backend/raad/core/events/redis_streams.
        #: RedisStreamsBrokerPort`, and this service's sibling relay/gateway publisher) - a single
        #: unbounded writer is enough to grow the stream past Redis's `maxmemory` on its own,
        #: which under the deliberate `noeviction` policy makes every subsequent `XADD` fail and
        #: stops the whole event backbone. Measured live before this fix: 301k entries / ~223 MB
        #: against a 256 MB ceiling. `0` disables trimming (the previous, unbounded behavior).
        self._max_length = max_length

    async def _xadd(self, fields: dict) -> None:
        """Single `XADD` chokepoint so stream trimming is applied identically to every event
        this publisher writes (see `_max_length`)."""
        if self._max_length > 0:
            await self._redis.xadd(
                self._stream_name, fields, maxlen=self._max_length, approximate=True
            )
            return
        await self._redis.xadd(self._stream_name, fields)

    async def publish(self, event: SessionEvent) -> None:
        await self._xadd(_fields_for(event))

    async def publish_stop_command(
        self,
        *,
        terminal_id: str,
        correlation_id: str,
        command: str,
        fields: dict[str, object],
    ) -> None:
        envelope = _envelope(
            event_type="Jt1078SignalCommandRequested",
            org_id=None,
            aggregate_type="Device",
            aggregate_id=terminal_id,
            occurred_at=datetime.now(timezone.utc),
            correlation_id=correlation_id,
            payload={
                "terminal_id": terminal_id,
                "correlation_id": correlation_id,
                "command": command,
                "fields": fields,
            },
        )
        await self._xadd(envelope)
