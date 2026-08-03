"""Unit tests for `core.health.service.HealthCheckService` (Priority 1 Item 5,
`PROJECT_STATUS.md`). Stdlib `unittest` — no `pytest`. Minimal fakes standing in for
`sqlalchemy.ext.asyncio.AsyncEngine`/`redis.asyncio.Redis` (only the one method each check
actually calls), mirroring `test_tracking_redis_latest_position.py`'s established `FakeRedis`
pattern — no real database/Redis connection.
"""

from __future__ import annotations

import unittest

from redis.exceptions import RedisError

from raad.core.health.service import HealthCheckService


class FakeAsyncConnection:
    def __init__(self, *, raises: bool = False) -> None:
        self._raises = raises

    async def execute(self, statement):  # noqa: ANN001 - matches AsyncConnection.execute shape
        if self._raises:
            raise ConnectionError("simulated connection failure")
        return None

    async def __aenter__(self) -> "FakeAsyncConnection":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FakeEngine:
    def __init__(self, *, raises: bool = False) -> None:
        self._raises = raises

    def connect(self) -> FakeAsyncConnection:
        return FakeAsyncConnection(raises=self._raises)


class FakeRedisClient:
    def __init__(self, *, raises: bool = False) -> None:
        self._raises = raises

    async def ping(self) -> bool:
        if self._raises:
            raise RedisError("simulated connection failure")
        return True


class HealthCheckServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_not_configured(self) -> None:
        service = HealthCheckService(engine=None, redis_client=None, broker_client=None)
        status = await service.check_database()
        self.assertFalse(status.configured)
        self.assertIsNone(status.reachable)
        self.assertEqual(status.label, "not_configured")

    async def test_database_reachable(self) -> None:
        service = HealthCheckService(
            engine=FakeEngine(raises=False), redis_client=None, broker_client=None
        )
        status = await service.check_database()
        self.assertTrue(status.configured)
        self.assertTrue(status.reachable)
        self.assertEqual(status.label, "ok")

    async def test_database_unreachable(self) -> None:
        service = HealthCheckService(
            engine=FakeEngine(raises=True), redis_client=None, broker_client=None
        )
        status = await service.check_database()
        self.assertTrue(status.configured)
        self.assertFalse(status.reachable)
        self.assertEqual(status.label, "down")

    async def test_redis_not_configured(self) -> None:
        service = HealthCheckService(engine=None, redis_client=None, broker_client=None)
        status = await service.check_redis()
        self.assertFalse(status.configured)
        self.assertIsNone(status.reachable)
        self.assertEqual(status.label, "not_configured")

    async def test_redis_reachable(self) -> None:
        service = HealthCheckService(
            engine=None, redis_client=FakeRedisClient(raises=False), broker_client=None
        )
        status = await service.check_redis()
        self.assertTrue(status.reachable)
        self.assertEqual(status.label, "ok")

    async def test_redis_unreachable(self) -> None:
        service = HealthCheckService(
            engine=None, redis_client=FakeRedisClient(raises=True), broker_client=None
        )
        status = await service.check_redis()
        self.assertTrue(status.configured)
        self.assertFalse(status.reachable)
        self.assertEqual(status.label, "down")

    async def test_broker_checked_independently_of_redis(self) -> None:
        service = HealthCheckService(
            engine=None,
            redis_client=FakeRedisClient(raises=False),
            broker_client=FakeRedisClient(raises=True),
        )
        redis_status = await service.check_redis()
        broker_status = await service.check_broker()
        self.assertEqual(redis_status.label, "ok")
        self.assertEqual(broker_status.label, "down")


if __name__ == "__main__":
    unittest.main()
