"""`RedisCameraSignalStatePort` — the terminal's latest per-channel video-signal report, kept in
Redis with a TTL (ADR-0046 §1).

Mirrors `video.infra.recording_search.RedisRecordingSearchResultPort` (ADR-0044 §2): one JSON
string per key, the shared `decode_responses=True` cache client, keys namespaced by purpose. The
TTL is longer than the device-gateway's refresh interval (5 minutes), so the report never lapses
while the terminal is online, and an offline terminal's report expires to "unknown" instead of
being shown as current.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from redis.asyncio import Redis

from raad.modules.fleet_device.application.ports import CameraSignalReport, CameraSignalStatePort

DEFAULT_CAMERA_SIGNAL_TTL_SECONDS = 30 * 60


def _key(device_id: str) -> str:
    return f"fleet_device:camera_signal:{device_id}"


class RedisCameraSignalStatePort(CameraSignalStatePort):
    def __init__(
        self, redis_client: Redis, *, ttl_seconds: int = DEFAULT_CAMERA_SIGNAL_TTL_SECONDS
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    async def save(self, device_id: str, report: CameraSignalReport) -> None:
        await self._redis.set(
            _key(device_id),
            json.dumps(
                {
                    "loss_mask": report.loss_mask,
                    "occlusion_mask": report.occlusion_mask,
                    "reported_at": report.reported_at.isoformat(),
                }
            ),
            ex=self._ttl_seconds,
        )

    async def get_many(self, device_ids: Sequence[str]) -> dict[str, CameraSignalReport]:
        ids = list(dict.fromkeys(device_ids))
        if not ids:
            return {}
        values = await self._redis.mget([_key(device_id) for device_id in ids])
        reports: dict[str, CameraSignalReport] = {}
        for device_id, raw in zip(ids, values):
            if raw is None:
                continue
            payload = json.loads(raw)
            reports[device_id] = CameraSignalReport(
                loss_mask=int(payload["loss_mask"]),
                occlusion_mask=payload.get("occlusion_mask"),
                reported_at=datetime.fromisoformat(payload["reported_at"]),
            )
        return reports
