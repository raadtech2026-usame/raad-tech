"""`RedisVideoSignalingConsumer` — the "Command direction (Backend -> device, via device-gateway)"
half of ADR-0024 §8. Mirrors `registry/redis_device_registry_consumer.RedisDeviceRegistryConsumer`'s
exact shape (own consumer group on the same shared `raad:events` stream, ack-everything/apply-only-
relevant, no retry/dead-letter — a missed or malformed command request is not silently retried
into a stuck loop, matching that module's own "self-healing, not business-critical the way a lost
notification/payment event would be" reasoning, extended here since a dropped video-signaling
command simply means the operator's live/playback request surfaces as `FAILED` and they retry
through the UI, the same "no automatic retry, a human re-requests" posture ADR-0024 §16 already
establishes for this exact failure family).

**Wire contract this consumer expects — the reference definition, since no backend publisher
exists yet this phase** (a future `Jt1078RelayAdapter`/`VideoProviderPort` binding is the natural
producer, not built here — see this deployable's own `docs/architecture/adr/
0024-jt1078-video-relay-architecture.md` §8, and this module's own docstring on why the *backend*
sends structured fields, never pre-encoded wire bytes):

```json
{
  "event_type": "Jt1078SignalCommandRequested",
  "payload": {
    "terminal_id": "<JT/T 808 terminal phone>",
    "correlation_id": "<opaque string the requester can trace a result back by>",
    "command": "live_video_request | live_video_control | live_video_status_notify |
                 query_resource_list | playback_request | playback_control |
                 query_av_attributes",
    "fields": { ... command-specific, see `_BUILDERS` below ... }
  }
}
```

`fields` carries plain JSON-compatible values — any `datetime`-typed field
(`start_time`/`end_time`/`seek_position`) is an ISO-8601 string, parsed here before constructing
the matching `commands.video_signaling` dataclass. A missing/unrecognized `command` value, or a
`fields` dict missing a required key, is logged and the message acked-but-dropped — the same
"malformed input can't be silently accepted, but also can't crash a shared consumer loop" posture
every other broker consumer in this deployable already takes.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Callable

from redis.asyncio import Redis

from src.logging_setup import get_logger, log_with_fields
from src.vendors.jt808.commands.av_attributes import encode_query_av_attributes
from src.vendors.jt808.commands.command_sender import CommandSender
from src.vendors.jt808.commands.video_signaling import (
    LiveVideoControl,
    LiveVideoRequest,
    LiveVideoStatusNotify,
    PlaybackControl,
    PlaybackRequest,
    QueryResourceList,
    encode_live_video_control,
    encode_live_video_request,
    encode_live_video_status_notify,
    encode_playback_control,
    encode_playback_request,
    encode_query_resource_list,
)
from src.vendors.jt808.dispatcher import message_ids

logger = get_logger("device_gateway.commands.video_signaling_consumer")

DEFAULT_STREAM_NAME = "raad:events"
DEFAULT_GROUP_NAME = "device-gateway-video-commands"

_RELEVANT_EVENT_TYPE = "Jt1078SignalCommandRequested"


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _build_live_video_request(fields: dict[str, Any]) -> tuple[int, bytes]:
    request = LiveVideoRequest(
        server_ip=fields["server_ip"],
        tcp_port=fields["tcp_port"],
        udp_port=fields["udp_port"],
        logical_channel=fields["logical_channel"],
        data_type=fields["data_type"],
        stream_type=fields["stream_type"],
    )
    return message_ids.LIVE_VIDEO_REQUEST, encode_live_video_request(request)


def _build_live_video_control(fields: dict[str, Any]) -> tuple[int, bytes]:
    control = LiveVideoControl(
        logical_channel=fields["logical_channel"],
        control=fields["control"],
        close_av_type=fields.get("close_av_type", 0),
        switch_stream_type=fields.get("switch_stream_type", 0),
    )
    return message_ids.LIVE_VIDEO_CONTROL, encode_live_video_control(control)


def _build_live_video_status_notify(fields: dict[str, Any]) -> tuple[int, bytes]:
    notify = LiveVideoStatusNotify(
        logical_channel=fields["logical_channel"],
        packet_loss_rate_percent=fields["packet_loss_rate_percent"],
    )
    return message_ids.LIVE_VIDEO_STATUS_NOTIFY, encode_live_video_status_notify(notify)


def _build_query_resource_list(fields: dict[str, Any]) -> tuple[int, bytes]:
    query = QueryResourceList(
        logical_channel=fields["logical_channel"],
        start_time=_parse_dt(fields.get("start_time")),
        end_time=_parse_dt(fields.get("end_time")),
        alarm_flag_filter=fields.get("alarm_flag_filter", 0),
        resource_type=fields["resource_type"],
        stream_type=fields["stream_type"],
        storage_type=fields["storage_type"],
    )
    return message_ids.QUERY_RESOURCE_LIST, encode_query_resource_list(query)


def _build_playback_request(fields: dict[str, Any]) -> tuple[int, bytes]:
    request = PlaybackRequest(
        server_ip=fields["server_ip"],
        tcp_port=fields["tcp_port"],
        udp_port=fields["udp_port"],
        logical_channel=fields["logical_channel"],
        av_type=fields["av_type"],
        stream_type=fields["stream_type"],
        storage_type=fields["storage_type"],
        playback_mode=fields["playback_mode"],
        speed_multiplier=fields.get("speed_multiplier", 0),
        start_time=_parse_dt(fields["start_time"]),
        end_time=_parse_dt(fields["end_time"]),
    )
    return message_ids.PLAYBACK_REQUEST, encode_playback_request(request)


def _build_playback_control(fields: dict[str, Any]) -> tuple[int, bytes]:
    control = PlaybackControl(
        av_channel=fields["av_channel"],
        control=fields["control"],
        speed_multiplier=fields.get("speed_multiplier", 0),
        seek_position=_parse_dt(fields.get("seek_position")),
    )
    return message_ids.PLAYBACK_CONTROL, encode_playback_control(control)


def _build_query_av_attributes(fields: dict[str, Any]) -> tuple[int, bytes]:
    # ADR-0030 — `commands/av_attributes.py`'s own channel-*count* discovery pair, distinct from
    # `_build_query_resource_list` above. `0x9003`'s body is empty (§6.1.1), so `fields` is
    # unused — kept as a parameter only so this function's shape matches every other entry in
    # `_BUILDERS` (a uniform `dict[str, Any] -> tuple[int, bytes]` callable).
    del fields
    return message_ids.QUERY_AV_ATTRIBUTES, encode_query_av_attributes()


_BUILDERS: dict[str, Callable[[dict[str, Any]], tuple[int, bytes]]] = {
    "live_video_request": _build_live_video_request,
    "live_video_control": _build_live_video_control,
    "live_video_status_notify": _build_live_video_status_notify,
    "query_resource_list": _build_query_resource_list,
    "playback_request": _build_playback_request,
    "playback_control": _build_playback_control,
    "query_av_attributes": _build_query_av_attributes,
}


class RedisVideoSignalingConsumer:
    def __init__(
        self,
        redis_client: Redis,
        *,
        command_sender: CommandSender,
        stream_name: str = DEFAULT_STREAM_NAME,
        group_name: str = DEFAULT_GROUP_NAME,
        consumer_name: str = "device-gateway-1",
        batch_size: int = 50,
        block_ms: int = 1000,
    ) -> None:
        self._redis = redis_client
        self._command_sender = command_sender
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
        """One read pass. Returns the number of command requests actually forwarded (not the
        number of messages read/acked, which includes irrelevant ones)."""
        await self._ensure_group()
        response = await self._redis.xreadgroup(
            self._group_name,
            self._consumer_name,
            {self._stream_name: ">"},
            count=self._batch_size,
            block=self._block_ms,
        )
        forwarded = 0
        for _stream_name, messages in response or []:
            for message_id, fields in messages:
                forwarded += await self._process_one(fields)
                await self._redis.xack(self._stream_name, self._group_name, message_id)
        return forwarded

    async def _process_one(self, fields: dict[str, str]) -> int:
        data: dict[str, Any] = json.loads(fields["data"])
        if data.get("event_type") != _RELEVANT_EVENT_TYPE:
            return 0

        payload = data.get("payload") or {}
        terminal_id = payload.get("terminal_id")
        correlation_id = payload.get("correlation_id")
        command = payload.get("command")
        command_fields = payload.get("fields") or {}

        if not terminal_id or not correlation_id or command not in _BUILDERS:
            log_with_fields(
                logger,
                30,
                "video_signal_command_rejected",
                reason="missing_or_unknown_fields",
                command=command,
            )
            return 0

        try:
            message_id, body = _BUILDERS[command](command_fields)
        except (KeyError, TypeError, ValueError) as exc:
            log_with_fields(
                logger,
                30,
                "video_signal_command_rejected",
                reason="malformed_fields",
                command=command,
                error=str(exc),
            )
            return 0

        await self._command_sender.send(
            terminal_id=terminal_id,
            message_id=message_id,
            body=body,
            correlation_id=correlation_id,
        )
        log_with_fields(
            logger,
            # INFO, not DEBUG (2026-09-02): a platform-issued command actually reaching a device
            # is the symmetric counterpart of `command_acknowledged` (already INFO,
            # `handlers/command_ack_handler.py`) and is exactly as low-volume - once per session
            # request, never per frame. At DEBUG it was invisible under this service's own
            # hardcoded INFO level, which made "was 0x9101 even sent for this channel?"
            # unanswerable from logs while diagnosing media sessions that never establish.
            20,
            "video_signal_command_forwarded",
            terminal_id=terminal_id,
            command=command,
            correlation_id=correlation_id,
            message_id=f"0x{message_id:04x}",
        )
        return 1

    async def run_forever(self) -> None:
        """Same fix, same live incident, as `registry/redis_device_registry_consumer.
        RedisDeviceRegistryConsumer.run_forever`'s own docstring: an unprotected `while True`
        here means any transient Redis error permanently and silently kills all further
        `Jt1078SignalCommandRequested` delivery (including the ADR-0030 `query_av_attributes`
        discovery request) for the rest of this process's life, with no error ever logged."""
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001 - a transient Redis error must not kill this loop
                log_with_fields(logger, 40, "video_signaling_poll_failed", error=str(exc))
                await asyncio.sleep(1.0)
