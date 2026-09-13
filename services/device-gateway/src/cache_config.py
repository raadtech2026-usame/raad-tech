"""Device-gateway cache configuration — root-cause fix, RAAD Live Tracking wrong-location
investigation.

**The bug this closes.** `DeviceGateway` previously had only one Redis connection concept
(`BrokerConfig`/`DEVICE_GATEWAY_BROKER_URL`) and used it for *everything*, including
`RedisLatestPositionWriter`'s `vehicle:{id}:last` snapshot write. In this stack's own documented
db-split convention (CLAUDE.md Permanent Engineering Lessons: "broker and cache split onto
separate logical Redis DBs (0 cache / 1 broker)"), `DEVICE_GATEWAY_BROKER_URL` points at **DB 1**
— so every `vehicle:{id}:last` write landed in DB 1, while the Business API's own
`RedisLatestPositionPort.get_latest` (`RAAD_REDIS__URL`) reads from **DB 0**. The write always
succeeded; it was simply invisible to the only reader, on every request, in every environment
that follows this stack's own db-split convention — confirmed live in this session: writes
verified present under `redis-cli -n 1 GET vehicle:<id>:last` and absent under `-n 0`.

A distinct, independently-configured env var (`DEVICE_GATEWAY_REDIS_URL`, mirroring
`DEVICE_GATEWAY_BROKER_URL`'s own precedent of not reusing the Business API's env var name across
deployables, `.claude/rules/architecture.md` #2) — set in `docker-compose.yml` to the same DB the
Business API's `RAAD_REDIS__URL` uses. Left unconfigured, `DeviceGateway` falls back to reusing
whatever Redis connection it already has (the broker client, or an injected test double) rather
than failing to write the snapshot at all — a deployment that hasn't adopted the cache/broker
DB-split convention still gets a working (if unsplit) cache, and every existing test that injects
one `redis_client` for everything keeps working unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CacheConfig:
    url: str | None = None

    @classmethod
    def from_env(cls) -> "CacheConfig":
        return cls(url=os.environ.get("DEVICE_GATEWAY_REDIS_URL") or None)
