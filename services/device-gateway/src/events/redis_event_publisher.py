"""`RedisEventPublisher` — the real, broker-backed `EventPublisher` implementation
(device-gateway Redis integration). Publishes every device-plane event
(`DevicePositionReported`/`DeviceOnline`/`DeviceOffline`/`DeviceAlarmRaised`) onto the **same**
shared `raad:events` Redis Stream (ADR-0008) the Business API's own `RedisStreamsBrokerPort`/
`RedisStreamsBrokerConsumer` already read from and write to — reusing existing infrastructure,
not standing up a second broker, exactly the roadmap's own B2 phase framing ("publishing onto
the same Redis Streams instance the Business API already uses").

**Wire envelope — deliberately byte-for-byte compatible with `backend/raad/core/events/
redis_streams.py`'s own `_event_to_fields`/`_fields_to_event`**, even though these are two
separate deployables with no shared Python code: a single Redis Streams field named `data`,
holding a JSON blob with exactly the fields `core.events.base.DomainEvent` has (`event_id`,
`event_type`, `version`, `occurred_at`, `org_id`, `correlation_id`, `payload`, `aggregate_type`,
`aggregate_id`). Getting this wrong would silently break `tracking.events.subscribers.
DevicePositionReportedProcessor`'s ability to consume anything this publisher sends — there is
no compiler across the deployable boundary to catch a mismatch, so this shape is treated as a
strict, documented wire contract instead of re-derived from memory.

**`event_type`/`aggregate_type`/`aggregate_id` per event — a decision this module makes, no prior
precedent dictated it:**
- `DevicePositionReported` -> `event_type="DevicePositionReported"`, `aggregate_type="Vehicle"`,
  `aggregate_id=vehicle_id` (always present on this event — dropped entirely upstream otherwise,
  `handlers.location_handler`/`vendors.lsz.handlers.position_handler`'s own "authenticated session
  required" rule).
- `DeviceOnline`/`DeviceOffline`/`DeviceAlarmRaised` -> `aggregate_type="Device"`,
  `aggregate_id=terminal_id` (always present; `vehicle_id` on these three is optional per
  `DeviceSession`'s own typing and cannot reliably serve as an aggregate identity).

`event_id` is a fresh UUID4 per publish — this deployable has no ULID generator of its own, and
none is needed (`DomainEvent.event_id` carries no format requirement any known consumer enforces).

**Requires a `decode_responses=True` client** (verified against `redis.asyncio.Redis`'s actual
method signatures, redis-py 8.0.1) — this class passes plain `str` values to `xadd`; a client
constructed without `decode_responses=True` would still *accept* them (redis-py encodes `str`
values on write regardless), but would return `bytes` on any subsequent *read* of the same keys by
other components sharing the connection (e.g. `RedisDeviceRegistryConsumer` reading this same
stream). `gateway.DeviceGateway._build_redis_client()` already sets this; any other caller
constructing a client directly for this class must do the same.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

from src.events.device_alarm_raised import DeviceAlarmRaised
from src.events.device_auth_code_issued import DeviceAuthCodeIssued
from src.events.device_av_attributes_reported import DeviceAvAttributesReported
from src.events.device_command_result import DeviceCommandResult
from src.events.device_offline import DeviceOffline
from src.events.device_online import DeviceOnline
from src.events.device_position_reported import DevicePositionReported
from src.events.device_resource_list_reported import DeviceResourceListReported
from src.events.publisher_port import DeviceEvent, EventPublisher

DEFAULT_STREAM_NAME = "raad:events"


def _envelope(
    *,
    event_type: str,
    org_id: str | None,
    aggregate_type: str,
    aggregate_id: str,
    occurred_at: datetime,
    payload: dict[str, Any],
    correlation_id: str | None = None,
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


def _fields_for(event: DeviceEvent) -> dict[str, str]:
    if isinstance(event, DevicePositionReported):
        return _envelope(
            event_type="DevicePositionReported",
            org_id=event.organization_id,
            aggregate_type="Vehicle",
            aggregate_id=event.vehicle_id,
            occurred_at=event.event_time,
            payload={
                "organization_id": event.organization_id,
                "vehicle_id": event.vehicle_id,
                "device_id": event.device_id,
                "terminal_id": event.terminal_id,
                "trip_id": event.trip_id,
                "latitude": event.latitude,
                "longitude": event.longitude,
                "speed_kph": event.speed_kph,
                "heading_deg": event.heading_deg,
                "alarm_flags": event.alarm_flags,
                "event_time": event.event_time.isoformat(),
                "is_backfill": event.is_backfill,
            },
        )
    if isinstance(event, DeviceOnline):
        return _envelope(
            event_type="DeviceOnline",
            org_id=event.organization_id,
            aggregate_type="Device",
            aggregate_id=event.terminal_id,
            occurred_at=event.event_time,
            payload={
                "organization_id": event.organization_id,
                "vehicle_id": event.vehicle_id,
                "device_id": event.device_id,
                "terminal_id": event.terminal_id,
            },
        )
    if isinstance(event, DeviceOffline):
        return _envelope(
            event_type="DeviceOffline",
            org_id=event.organization_id,
            aggregate_type="Device",
            aggregate_id=event.terminal_id,
            occurred_at=event.event_time,
            payload={
                "organization_id": event.organization_id,
                "vehicle_id": event.vehicle_id,
                "device_id": event.device_id,
                "terminal_id": event.terminal_id,
                "reason": event.reason,
            },
        )
    if isinstance(event, DeviceAlarmRaised):
        return _envelope(
            event_type="DeviceAlarmRaised",
            org_id=event.organization_id,
            aggregate_type="Device",
            aggregate_id=event.terminal_id,
            occurred_at=event.event_time,
            payload={
                "organization_id": event.organization_id,
                "vehicle_id": event.vehicle_id,
                "device_id": event.device_id,
                "terminal_id": event.terminal_id,
                "alarm_type": event.alarm_type,
                "alarm_flags": event.alarm_flags,
            },
        )
    if isinstance(event, DeviceAuthCodeIssued):
        return _envelope(
            event_type="DeviceAuthCodeIssued",
            org_id=event.organization_id,
            aggregate_type="Device",
            aggregate_id=event.device_id,
            occurred_at=event.event_time,
            payload={
                "organization_id": event.organization_id,
                "vehicle_id": event.vehicle_id,
                "device_id": event.device_id,
                "terminal_id": event.terminal_id,
                "auth_key_hash": event.auth_key_hash,
            },
        )
    if isinstance(event, DeviceCommandResult):
        return _envelope(
            event_type="DeviceCommandResult",
            org_id=event.organization_id,
            aggregate_type="Device",
            aggregate_id=event.terminal_id,
            occurred_at=event.event_time,
            correlation_id=event.correlation_id,
            payload={
                "organization_id": event.organization_id,
                "vehicle_id": event.vehicle_id,
                "device_id": event.device_id,
                "terminal_id": event.terminal_id,
                "correlation_id": event.correlation_id,
                "message_id": event.message_id,
                "success": event.success,
                "reason": event.reason,
            },
        )
    if isinstance(event, DeviceResourceListReported):
        return _envelope(
            event_type="DeviceResourceListReported",
            org_id=event.organization_id,
            aggregate_type="Device",
            aggregate_id=event.terminal_id,
            occurred_at=event.event_time,
            correlation_id=event.correlation_id,
            payload={
                "organization_id": event.organization_id,
                "vehicle_id": event.vehicle_id,
                "device_id": event.device_id,
                "terminal_id": event.terminal_id,
                "correlation_id": event.correlation_id,
                "total_resource_count": event.total_resource_count,
                "items": list(event.items),
            },
        )
    if isinstance(event, DeviceAvAttributesReported):
        return _envelope(
            event_type="DeviceAvAttributesReported",
            org_id=event.organization_id,
            aggregate_type="Device",
            aggregate_id=event.terminal_id,
            occurred_at=event.event_time,
            correlation_id=event.correlation_id,
            payload={
                "organization_id": event.organization_id,
                "vehicle_id": event.vehicle_id,
                "device_id": event.device_id,
                "terminal_id": event.terminal_id,
                "correlation_id": event.correlation_id,
                "max_video_channels": event.max_video_channels,
                "max_audio_channels": event.max_audio_channels,
                "input_audio_codec": event.input_audio_codec,
                "input_audio_channels": event.input_audio_channels,
                "input_audio_sample_rate": event.input_audio_sample_rate,
                "input_audio_sample_bits": event.input_audio_sample_bits,
                "audio_frame_length": event.audio_frame_length,
                "supports_audio_output": event.supports_audio_output,
                "video_codec": event.video_codec,
            },
        )
    raise TypeError(f"Unrecognized device-plane event type: {type(event)!r}")


class RedisEventPublisher(EventPublisher):
    def __init__(self, redis_client: Redis, *, stream_name: str = DEFAULT_STREAM_NAME) -> None:
        self._redis = redis_client
        self._stream_name = stream_name

    async def publish(self, event: DeviceEvent) -> None:
        await self._redis.xadd(self._stream_name, _fields_for(event))
