"""Real dependency checks for `/health/ready` (Priority 1 Item 5, `PROJECT_STATUS.md`). Closes
Known Issue #3: the route previously only confirmed `Settings` had loaded, never actually
touching the database or Redis — a broken DB connection or an unreachable *configured* Redis
would still report "ready", the worst possible failure mode for a readiness probe (an
orchestrator routing real traffic to a process that can't serve it).

Always constructible, even with every dependency unconfigured — the same "service always
constructible, individual methods handle an unbound port" pattern
`TrackingApplicationService`/`VideoApplicationService` already establish elsewhere in this
codebase — so `interfaces/http/health.py` never needs to special-case a missing service, only a
missing *check result*.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_CHECK_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class DependencyStatus:
    """`reachable` is `None` exactly when `configured` is `False` — a dependency that was never
    configured was never "checked" at all, distinct from one that was configured and failed."""

    configured: bool
    reachable: bool | None

    @property
    def label(self) -> str:
        if not self.configured:
            return "not_configured"
        return "ok" if self.reachable else "down"


class HealthCheckService:
    def __init__(
        self,
        *,
        engine: AsyncEngine | None,
        redis_client: Redis | None,
        broker_client: Redis | None,
    ) -> None:
        self._engine = engine
        self._redis_client = redis_client
        self._broker_client = broker_client

    async def check_database(self) -> DependencyStatus:
        if self._engine is None:
            return DependencyStatus(configured=False, reachable=None)
        try:
            async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
                async with self._engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            return DependencyStatus(configured=True, reachable=True)
        except Exception:
            # Deliberately broad: any failure mode (connection refused, auth failure, timeout,
            # pool exhaustion) means "not ready to serve traffic," which is all this probe needs
            # to know — the real error is already logged wherever the failing query/connection
            # attempt itself logs, this check only needs the boolean outcome.
            return DependencyStatus(configured=True, reachable=False)

    async def check_redis(self) -> DependencyStatus:
        return await self._ping(self._redis_client)

    async def check_broker(self) -> DependencyStatus:
        return await self._ping(self._broker_client)

    @staticmethod
    async def _ping(client: Redis | None) -> DependencyStatus:
        if client is None:
            return DependencyStatus(configured=False, reachable=None)
        try:
            async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
                await client.ping()
            return DependencyStatus(configured=True, reachable=True)
        except (RedisError, TimeoutError):
            return DependencyStatus(configured=True, reachable=False)
