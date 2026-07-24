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
`DeviceRetired`/`DeviceAssignedToVehicle`/`DeviceUnassignedFromVehicle`/`DeviceReassigned` are
actually applied to the projection, everything else is acknowledged and discarded.

**No retry/dead-letter handling** (unlike the Business API's own `RedisStreamsBrokerConsumer`) —
a missed or misapplied registry update is self-healing: the next relevant event for the same
device (or a process restart re-reading from the group's last-acked position) corrects it, and
nothing here is business-critical the way a lost notification or payment event would be. Kept
deliberately simpler than the Business API's consumer for exactly that reason.
"""

from __future__ import annotations

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
        while True:
            await self.poll_once()
