"""`CommandResultConsumer` — reads the device-gateway's `DeviceCommandResult` events so the relay
learns, within a second, that one of its start commands never reached the terminal.

**Why (production audit, 2026-09-26).** When the terminal has no open JT/T 808 connection, the
gateway does not send the command and publishes `DeviceCommandResult(success=False,
reason="device_offline")`. Nothing consumed it, so the relay kept the new stream waiting for a media
connection that could not come, and the operator watched "Connecting" for the full 30 s ingest
timeout (08:09 and 08:37 that day). Now the stream's sessions fail at once with
`device_offline`, and the browser moves straight to its "Device offline" state.

Only `device_offline` is acted on: a `timed_out` start was delivered and the terminal may still
dial in, which the ingest timeout already covers.

A consumer group on the shared `raad:events` stream (the same pattern as device-gateway's
`RedisVideoSignalingConsumer`), created at `$`, so a relay restart never replays old results. The
loop catches and logs every per-iteration error (CLAUDE.md, Permanent Engineering Lessons: an
unprotected `run_forever` dies silently on the first transient Redis error).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from redis.asyncio import Redis

from src.logging_setup import get_logger, log_with_fields
from src.session.session_manager import SessionManager

logger = get_logger("jt1078_relay.session.command_results")

DEFAULT_STREAM_NAME = "raad:events"
DEFAULT_GROUP_NAME = "jt1078-relay-command-results"
_RELEVANT_EVENT_TYPE = "DeviceCommandResult"
_UNDELIVERED_REASON = "device_offline"


class CommandResultConsumer:
    def __init__(
        self,
        redis_client: Redis,
        *,
        session_manager: SessionManager,
        stream_name: str = DEFAULT_STREAM_NAME,
        group_name: str = DEFAULT_GROUP_NAME,
        consumer_name: str = "jt1078-relay",
        batch_size: int = 100,
        block_ms: int = 1000,
    ) -> None:
        self._redis = redis_client
        self._session_manager = session_manager
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
                self._stream_name, self._group_name, id="$", mkstream=True
            )
        except Exception as exc:  # noqa: BLE001 - BUSYGROUP means it already exists
            if "BUSYGROUP" not in str(exc):
                raise
        self._group_ready = True

    async def poll_once(self) -> int:
        """One read pass. Returns how many streams were ended because their start was not
        delivered."""
        await self._ensure_group()
        response = await self._redis.xreadgroup(
            self._group_name,
            self._consumer_name,
            {self._stream_name: ">"},
            count=self._batch_size,
            block=self._block_ms,
        )
        ended = 0
        for _stream, messages in response or []:
            for message_id, fields in messages:
                try:
                    ended += await self._process_one(fields)
                finally:
                    await self._redis.xack(self._stream_name, self._group_name, message_id)
        return ended

    async def _process_one(self, fields: dict[str, str]) -> int:
        try:
            data: dict[str, Any] = json.loads(fields["data"])
        except (KeyError, TypeError, ValueError):
            return 0
        if data.get("event_type") != _RELEVANT_EVENT_TYPE:
            return 0
        payload = data.get("payload") or {}
        if payload.get("success") or payload.get("reason") != _UNDELIVERED_REASON:
            return 0
        correlation_id = payload.get("correlation_id") or ""
        if not await self._session_manager.handle_start_not_delivered(correlation_id):
            return 0
        log_with_fields(
            logger,
            20,
            "stream_ended_device_offline",
            correlation_id=correlation_id,
            terminal_id=payload.get("terminal_id"),
        )
        return 1

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a transient Redis error must not kill this loop
                log_with_fields(logger, 40, "command_result_poll_failed", error=str(exc))
                await asyncio.sleep(1.0)
