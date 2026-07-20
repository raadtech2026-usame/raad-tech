"""PostgreSQL-backed integration test for `transport_ops`'s `SqlAlchemyDriverRepository`
(Phase 10.8). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyTransportOpsUnitOfWork` and the
live migrated schema (Alembic head `8bde77c847c0`), not fakes — mirroring
`test_transport_ops_parent_repository.py`'s skip-guard/cleanup pattern exactly.

`Driver` has no documented safety-critical DB-level invariant analogous to Fleet Device's
partial-unique-index or IAM's duplicate-email constraint (Database Design §6.1 declares no
unique constraint on `drivers` beyond the primary key) — so what's meaningful to prove here,
that no in-memory unit test can, is the round trip through the real identity-map/
`flush_tracked_changes` mechanics `infra/repositories.py`'s module docstring describes: a
`get()` returns a detached domain object, mutating it in place and calling `commit()` (without a
second `add()`) must still persist the change, because the repository re-projects tracked
domain objects onto their ORM rows before the session flush.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable, per this project's established live-verification
posture. Every test inserts rows tagged with a unique per-run marker and deletes them in
`tearDown`, leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.audit.writer import AuditWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.domain.entities import Driver
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    OrganizationId,
    UserId,
)
from raad.modules.transport_ops.infra.repositories import (
    SqlAlchemyTransportOpsUnitOfWork,
)


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class DriverRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_ids:
                await conn.execute(
                    text("DELETE FROM drivers WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_add_then_get_round_trips_all_fields(self) -> None:
        # organization_id/user_id are CHAR(26) columns (Database Design §6.1): a shorter opaque
        # string like f"org-{self.tag}" would round-trip space-padded by PostgreSQL's fixed-width
        # CHAR semantics, so use ULID-shaped (26-char) values here, matching what production
        # OrganizationId/UserId values actually look like.
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                license_no=f"DL-{self.tag}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            driver_id = driver.id
            self._created_ids.append(str(driver_id))

        async with self._new_uow() as uow:
            fetched = await uow.drivers.get(driver_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(str(fetched.user_id), user_id)
        self.assertEqual(fetched.license_no, f"DL-{self.tag}")
        self.assertEqual(fetched.status, DriverStatus.ACTIVE)

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        """Proves the identity-map/`flush_tracked_changes` bridge described in
        `infra/repositories.py`'s module docstring: `get()` returns a detached domain object,
        and calling a lifecycle method on it followed by `commit()` (no `add()` call) must still
        persist, because the repository re-projects the tracked object onto its ORM row.
        """
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                license_no=f"DL-{self.tag}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            driver_id = driver.id
            self._created_ids.append(str(driver_id))

        async with self._new_uow() as uow:
            loaded = await uow.drivers.get(driver_id)
            loaded.disable(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.drivers.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.drivers.get(driver_id)

        self.assertEqual(refetched.status, DriverStatus.INACTIVE)

    async def test_list_all_includes_newly_added_driver(self) -> None:
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                license_no=f"List Test {self.tag}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(driver.id))

        async with self._new_uow() as uow:
            all_drivers = await uow.drivers.list_all()

        self.assertIn(str(driver.id), {str(d.id) for d in all_drivers})

    async def test_get_missing_driver_returns_none(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.drivers.get(DriverId(self.id_generator.new_id()))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
