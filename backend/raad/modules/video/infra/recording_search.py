"""`RedisRecordingSearchResultPort` — the short-lived store a recording search's asynchronous
result lands in (ADR-0044 §2).

**Redis, with a TTL, deliberately not a PostgreSQL table.** A recording list is a momentary fact
about the *terminal's own* storage, not a RAAD record: persisting it would create a second,
immediately-stale copy of the MDVR's archive index, which is exactly the "the VPS becomes the
video archive" outcome ADR-0044 exists to prevent. An expired search is simply searched again.

Mirrors `tracking.infra.adapters.RedisLatestPositionPort`'s shape (one JSON string per key, the
same `decode_responses=True` client contract, keys namespaced by purpose), which is this
codebase's established pattern for a read-model that lives in Redis rather than the database.
"""

from __future__ import annotations

import json
from datetime import datetime

from redis.asyncio import Redis

from raad.modules.video.application.ports import (
    RecordingSearchResult,
    RecordingSearchResultPort,
    RecordingSegment,
)

#: 15 minutes: long enough for an operator to read a result, pick a segment and start playback,
#: short enough that a stale archive index can never be mistaken for the device's current one.
DEFAULT_SEARCH_TTL_SECONDS = 15 * 60


def _key(search_id: str) -> str:
    return f"video:recording_search:{search_id}"


class RedisRecordingSearchResultPort(RecordingSearchResultPort):
    def __init__(self, redis_client: Redis, *, ttl_seconds: int = DEFAULT_SEARCH_TTL_SECONDS) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    async def remember_request(
        self, *, search_id: str, organization_id: str, device_id: str
    ) -> None:
        await self._write(
            search_id,
            {
                "search_id": search_id,
                "organization_id": organization_id,
                "device_id": device_id,
                "segments": None,
            },
        )

    async def save_segments(
        self, *, search_id: str, segments: tuple[RecordingSegment, ...]
    ) -> None:
        raw = await self._redis.get(_key(search_id))
        if raw is None:
            # Unknown or expired search: the device answered something nobody is waiting for any
            # more. Dropped rather than resurrected - a result with no remembered request carries
            # no organization to scope it by, so storing it would be unscoped data.
            return
        payload = json.loads(raw)
        payload["segments"] = [
            {
                "channel_no": segment.channel_no,
                "start_time": segment.start_time.isoformat(),
                "end_time": segment.end_time.isoformat(),
                "alarm_flag": segment.alarm_flag,
                "resource_type": segment.resource_type,
                "stream_type": segment.stream_type,
                "storage_type": segment.storage_type,
                "size_bytes": segment.size_bytes,
            }
            for segment in segments
        ]
        # Rewritten with a fresh TTL: the clock that matters to an operator starts when the
        # answer arrives, not when the question was asked.
        await self._write(search_id, payload)

    async def get(self, search_id: str) -> RecordingSearchResult | None:
        raw = await self._redis.get(_key(search_id))
        if raw is None:
            return None
        payload = json.loads(raw)
        segments = payload.get("segments")
        return RecordingSearchResult(
            search_id=payload["search_id"],
            organization_id=payload["organization_id"],
            device_id=payload["device_id"],
            segments=(
                None
                if segments is None
                else tuple(
                    RecordingSegment(
                        channel_no=item["channel_no"],
                        start_time=datetime.fromisoformat(item["start_time"]),
                        end_time=datetime.fromisoformat(item["end_time"]),
                        alarm_flag=item["alarm_flag"],
                        resource_type=item["resource_type"],
                        stream_type=item["stream_type"],
                        storage_type=item["storage_type"],
                        size_bytes=item["size_bytes"],
                    )
                    for item in segments
                )
            ),
        )

    async def _write(self, search_id: str, payload: dict) -> None:
        await self._redis.set(_key(search_id), json.dumps(payload), ex=self._ttl_seconds)
