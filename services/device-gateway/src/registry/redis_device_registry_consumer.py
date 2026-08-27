"""`RedisDeviceRegistryConsumer` — keeps a `DeviceRegistryProjection` current by reading the
**same** shared `raad:events` Redis Stream (ADR-0008) `RedisEventPublisher` publishes onto and the
Business API's own `RedisStreamsBrokerPort` already writes to — its own, distinct consumer group
(`device-gateway-registry` by default) so it receives an independent copy of every event, exactly
like the Business API's `ws-tracking`/`notification-worker` consumer groups each do today.

**Wire format — decoded with the same field names `backend/raad/core/events/redis_streams.py`'s
`_fields_to_event` reads** (a single `data` field holding the JSON-encoded envelope); see
`events/redis_event_publisher.py`'s own module docstring for why this is a strict, documented
cross-deployable contract rather than shared code.

**Acknowledges every message on the shared stream, not just the ones it cares about** — this
consumer group must keep pace with every event `raad:events` ever carries (position reports,
notifications, billing, everything), or its own unacknowledged/pending-entries list would grow
without bound; only `DeviceRegistered`/`DeviceActivated`/`DeviceSuspended`/`DeviceReactivated`/
`DeviceRetired`/`DeviceAssignedToVehicle`/`DeviceUnassignedFromVehicle`/`DeviceReassigned`/
`DeviceAuthCodeIssued` are actually applied to the projection, everything else is acknowledged and
discarded.

**No retry/dead-letter handling** (unlike the Business API's own `RedisStreamsBrokerConsumer`) —
a missed or misapplied registry update is self-healing: the next relevant event for the same
device (or a process restart re-reading from the group's last-acked position) corrects it, and
nothing here is business-critical the way a lost notification or payment event would be. Kept
deliberately simpler than the Business API's consumer for exactly that reason.

**Requires a `decode_responses=True` client** (verified against `redis.asyncio.Redis`'s actual
method signatures, redis-py 8.0.1) — `_process_one` indexes `fields["data"]` with a `str` key and
`json.loads`s a `str` value; a client without `decode_responses=True` would hand back `bytes` for
both the field name and value, and `fields["data"]` would raise `KeyError` (the real key would be
`b"data"`, not `"data"`). `gateway.DeviceGateway._build_redis_client()` already sets this.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from redis.asyncio import Redis

from src.logging_setup import get_logger, log_with_fields
from src.registry.device_registry_projection import DeviceRegistryProjection

logger = get_logger("device_gateway.registry.consumer")

DEFAULT_STREAM_NAME = "raad:events"
DEFAULT_GROUP_NAME = "device-gateway-registry"

_RELEVANT_EVENT_TYPES = {
    "DeviceRegistered",
    "DeviceActivated",
    "DeviceSuspended",
    "DeviceReactivated",
    "DeviceRetired",
    "DeviceAssignedToVehicle",
    "DeviceUnassignedFromVehicle",
    "DeviceReassigned",
    # P0 #2 fix: previously excluded, which meant `replay_from_start` could never recover a
    # previously-minted `auth_key_hash` after a device-gateway restart -- see
    # `DeviceRegistryProjection.apply_event`'s own `DeviceAuthCodeIssued` branch.
    "DeviceAuthCodeIssued",
}


class RedisDeviceRegistryConsumer:
    def __init__(
        self,
        redis_client: Redis,
        *,
        projection: DeviceRegistryProjection,
        stream_name: str = DEFAULT_STREAM_NAME,
        group_name: str = DEFAULT_GROUP_NAME,
        consumer_name: str = "device-gateway-1",
        batch_size: int = 50,
        block_ms: int = 1000,
    ) -> None:
        self._redis = redis_client
        self._projection = projection
        self._stream_name = stream_name
        self._group_name = group_name
        self._consumer_name = consumer_name
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._group_ready = False

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self._redis.xgroup_create(
                self._stream_name, self._group_name, id="0", mkstream=True
            )
        except Exception as exc:  # noqa: BLE001 - redis-py raises a generic ResponseError
            if "BUSYGROUP" not in str(exc):
                raise
        self._group_ready = True

    async def replay_from_start(self) -> int:
        """**The fix for a real, production-blocking gap found live (2026-08-19): a
        device-gateway restart previously lost the entire registry projection for every
        already-provisioned device.** `DeviceRegistryProjection` is a plain in-memory `dict` —
        nothing about it survives a process restart. But the Redis consumer *group* this class
        reads through (`device-gateway-registry`) is itself durable state living in Redis: once
        created, its delivery cursor persists there across restarts, and `_ensure_group`'s own
        `BUSYGROUP` handling deliberately reuses that persisted cursor rather than resetting it.
        The result: `poll_once`'s `xreadgroup(..., {stream: ">"})` only ever returns messages
        *after* the group's last-acked position — on a fresh process with an empty in-memory
        projection but an already-caught-up group, that is nothing, forever, until some
        unrelated new event happens to touch a given device again. Confirmed live against the
        physical `LSZ-C5804DG-Q-F` bench unit: after a routine restart to deploy ADR-0030, a
        previously-registered, activated, vehicle-assigned device (already resolvable before the
        restart) started failing JT/T 808 `0x0100` with `terminal_not_found`, with 19000+ events
        already sitting acked-and-unread in `raad:events`.

        The fix: a **one-time, consumer-group-independent** full-stream read (`XRANGE`, not
        `XREADGROUP`) that rebuilds the projection from every event still in the stream, called
        once at startup *before* any vendor adapter starts accepting connections
        (`gateway.DeviceGateway.start`) — so no device can race a still-empty projection. This
        does not touch the consumer group's own cursor at all (`XRANGE` has no group semantics),
        so `poll_once`/`run_forever`'s ordinary incremental catch-up afterward is unaffected;
        every event type this consumer applies is idempotent last-write-wins state (an
        `is_active`/`vehicle_id` assignment, never a counter), so re-applying an event the
        incremental loop later re-delivers (there should be none, since the group's cursor
        already sits past everything this replay just read) would be harmless even if it
        happened.

        **Disclosed, not silently assumed away:** this reads the *entire* shared `raad:events`
        stream every time the process starts, filtering for the 9 event types this projection
        cares about out of every event type in this platform's entire vocabulary — proportional
        to total platform event volume, not to device count. Acceptable at this platform's
        current scale (this fix's own live verification replayed 19000+ events in well under a
        second); a stream large enough to make this slow would need a persisted/snapshotted
        projection instead, a larger change intentionally not attempted here."""
        applied = 0
        start = "-"
        while True:
            batch = await self._redis.xrange(
                self._stream_name, min=start, max="+", count=self._batch_size
            )
            if not batch:
                break
            for _message_id, fields in batch:
                applied += self._process_one(fields)
            start = f"({batch[-1][0]}"
            if len(batch) < self._batch_size:
                break
        log_with_fields(
            logger,
            20,
            "device_registry_replay_completed",
            events_applied=applied,
        )
        return applied

    async def poll_once(self) -> int:
        """One read pass. Returns the number of events actually applied to the projection
        (not the number of messages read/acked, which includes irrelevant ones)."""
        await self._ensure_group()
        response = await self._redis.xreadgroup(
            self._group_name,
            self._consumer_name,
            {self._stream_name: ">"},
            count=self._batch_size,
            block=self._block_ms,
        )
        applied = 0
        for _stream_name, messages in response or []:
            for message_id, fields in messages:
                applied += self._process_one(fields)
                await self._redis.xack(self._stream_name, self._group_name, message_id)
        return applied

    def _process_one(self, fields: dict[str, str]) -> int:
        data: dict[str, Any] = json.loads(fields["data"])
        event_type = data.get("event_type")
        if event_type not in _RELEVANT_EVENT_TYPES:
            return 0
        self._projection.apply_event(
            event_type=event_type,
            aggregate_id=data["aggregate_id"],
            org_id=data.get("org_id"),
            payload=data.get("payload") or {},
        )
        log_with_fields(
            logger,
            10,
            "device_registry_event_applied",
            event_type=event_type,
            aggregate_id=data["aggregate_id"],
        )
        return 1

    async def run_forever(self) -> None:
        """**A second real, production-blocking gap found live (2026-08-19), same incident as
        `replay_from_start` above.** This loop previously had no protection at all: any single
        exception from `poll_once` (a transient Redis error - connection reset, a `BusyLoading`
        reply while Redis reloads its dataset, anything) propagated straight out of this
        `while True`, silently killing the whole `asyncio.Task` for the rest of the process's
        life - nothing ever awaits or logs the result of a fire-and-forget task like this one
        until process shutdown, so the failure was completely invisible until then. Live-found
        via the sibling bug in `services/jt1078/src/session/session_request_server.py` (identical
        pattern, identical fix) - both are fixed together since they're the same class of gap.
        Matches this codebase's own established resilient-loop shape
        (`backend/raad/core/workers/base.py Worker._tick`: catch, log, never let one bad
        iteration kill the loop) - `poll_once`'s own per-message ack-then-apply semantics already
        make a retried poll safe to repeat."""
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001 - a transient Redis error must not kill this loop
                log_with_fields(logger, 40, "device_registry_poll_failed", error=str(exc))
                await asyncio.sleep(1.0)
