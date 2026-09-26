"""`RedisCameraSignalStatePort` — the terminal's latest per-channel video-signal report, kept in
Redis with a TTL (ADR-0046 §1).

Mirrors `video.infra.recording_search.RedisRecordingSearchResultPort` (ADR-0044 §2): one JSON
string per key, the shared `decode_responses=True` cache client, keys namespaced by purpose. The
TTL is long (30 days): which channels have a camera is physical installation, so the last report
is the best answer while the terminal is away, and the gateway publishes a fresh one on the first
position report of every new connection (~20 s after it comes back), which corrects any change made
while it was offline. A 30-minute TTL (the first version) meant a terminal back from a longer outage
showed every channel as "unknown" - all four tiles, streams on the channels with no camera - until
that first report (production, 2026-09-26 14:45:17). A terminal silent for 30 days reads "unknown".
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from redis.asyncio import Redis

from raad.modules.fleet_device.application.ports import CameraSignalReport, CameraSignalStatePort

DEFAULT_CAMERA_SIGNAL_TTL_SECONDS = 30 * 24 * 60 * 60


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
