"""PostgreSQL-backed integration test for `core.health.service.HealthCheckService` (Priority 1
Item 5, `PROJECT_STATUS.md`). Stdlib `unittest` — no `pytest`. **Requires a reachable
PostgreSQL** configured via `RAAD_DB__URL` (`.env`) — skipped entirely (not failed) when
unavailable, matching every other live-DB integration test in this suite.
"""

from __future__ import annotations

import unittest

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine
from raad.core.health.service import HealthCheckService


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class HealthCheckServiceLiveDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_check_database_against_real_reachable_postgres(self) -> None:
        service = HealthCheckService(engine=self.engine, redis_client=None, broker_client=None)
        status = await service.check_database()
        self.assertTrue(status.configured)
        self.assertTrue(status.reachable)
        self.assertEqual(status.label, "ok")

    async def test_check_database_reports_down_for_an_unreachable_host(self) -> None:
        """A real, live proof that a genuinely broken connection is correctly reported `down`,
        not just that a working one is reported `ok` — points at a real `AsyncEngine` built
        against a connection string that cannot possibly resolve/accept a connection, rather
        than mocking the failure."""
        from raad.core.config.settings import DbSettings

        broken_engine = build_engine(
            DbSettings(url="postgresql+asyncpg://raad:raad@localhost:1/nonexistent")
        )
        try:
            service = HealthCheckService(
                engine=broken_engine, redis_client=None, broker_client=None
            )
            status = await service.check_database()
            self.assertTrue(status.configured)
            self.assertFalse(status.reachable)
            self.assertEqual(status.label, "down")
        finally:
            await broken_engine.dispose()


if __name__ == "__main__":
    unittest.main()
