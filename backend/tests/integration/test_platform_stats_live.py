"""PostgreSQL-backed integration tests for ADR-0020 (Platform Analytics Read Model). Stdlib
`unittest` — no `pytest` (not an approved dependency) — against the live migrated schema, not
fakes, mirroring `test_fleet_device_repository.py`'s skip-guard/cleanup pattern exactly.

Covers two things no fake-backed unit test can: (1) the *real* `DeviceConnectivityProcessor`
(not a recording double) actually flips `devices.is_online` in the database on a real
`DeviceOnline`/`DeviceOffline` event, and the new `count_total`/`count_online` queries return
correct numbers against real seeded rows; (2) the *real*, DI-wired `PlatformStatsApplicationService`
(via `build_container`, mirroring `test_iam_repository.py`'s `SessionCapAdapterLiveSettingTests`
precedent from ADR-0019) runs the full four-module composition against a real database without
error. Exact counts aren't asserted for the composition test — this sandbox's dev database
carries arbitrary pre-existing rows from earlier session work — only structural/type sanity and
the effect of rows this test itself seeds and cleans up.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.di.bootstrap import build_container
from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import DeviceApplicationService
from raad.modules.fleet_device.domain.entities import Device
from raad.modules.fleet_device.domain.value_objects import (
    DeviceId,
    OrganizationId as FleetOrganizationId,
    TerminalId,
)
from raad.modules.fleet_device.events.subscribers import DeviceConnectivityProcessor
from raad.modules.fleet_device.infra.repositories import SqlAlchemyFleetDeviceUnitOfWork
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.platform_audit.application.services import PlatformStatsApplicationService


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class DeviceConnectivityLiveTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0020 §3: the real `DeviceConnectivityProcessor` against a real database."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.tag = uuid.uuid4().hex[:8]
        self._created_device_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_device_ids:
                await conn.execute(
                    text("DELETE FROM devices WHERE id = ANY(:ids)"),
                    {"ids": self._created_device_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyFleetDeviceUnitOfWork:
        return SqlAlchemyFleetDeviceUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed_device(self) -> str:
        async with self._new_uow() as uow:
            device = Device.register(
                id=DeviceId(self.id_generator.new_id()),
                organization_id=FleetOrganizationId(self.id_generator.new_id()),
                terminal_id=TerminalId(f"CONN-{self.tag}-{uuid.uuid4().hex[:6]}"),
                clock=SystemClock(),
            )
            uow.devices.add(device)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            self._created_device_ids.append(str(device.id))
            return str(device.id)

    def _make_container_with_real_uow(self) -> Container:
        # `DeviceApplicationService`/`FleetDeviceUnitOfWork` are resolved fresh per call inside
        # the real processor — a minimal container binding just what `DeviceConnectivityProcessor
        # .process()` actually resolves, mirroring `test_fleet_device_subscribers.py`'s own
        # fake-binding pattern but with the *real* service/UoW this time.
        container = Container()
        device_service = DeviceApplicationService(
            clock=SystemClock(), id_generator=self.id_generator
        )
        container.bind_singleton(DeviceApplicationService, device_service)
        container.bind_factory(FleetDeviceUnitOfWork, self._new_uow)
        return container

    async def test_device_online_event_flips_is_online_in_the_database(self) -> None:
        device_id = await self._seed_device()
        container = self._make_container_with_real_uow()
        processor = DeviceConnectivityProcessor("DeviceOnline", container)
        event = DomainEvent(
            event_id="evt-1",
            event_type="DeviceOnline",
            version=1,
            occurred_at=datetime.now(timezone.utc),
            org_id=None,
            correlation_id=None,
            payload={"device_id": device_id},
            aggregate_type="Device",
            aggregate_id=device_id,
        )

        await processor.process(event)

        async with self._new_uow() as uow:
            reloaded = await uow.devices.get(DeviceId(device_id))
        self.assertTrue(reloaded.is_online)
        self.assertIsNotNone(reloaded.last_seen_at)

    async def test_device_offline_event_clears_is_online_in_the_database(self) -> None:
        device_id = await self._seed_device()
        container = self._make_container_with_real_uow()
        await DeviceConnectivityProcessor("DeviceOnline", container).process(
            DomainEvent(
                event_id="evt-1",
                event_type="DeviceOnline",
                version=1,
                occurred_at=datetime.now(timezone.utc),
                org_id=None,
                correlation_id=None,
                payload={"device_id": device_id},
                aggregate_type="Device",
                aggregate_id=device_id,
            )
        )

        await DeviceConnectivityProcessor("DeviceOffline", container).process(
            DomainEvent(
                event_id="evt-2",
                event_type="DeviceOffline",
                version=1,
                occurred_at=datetime.now(timezone.utc),
                org_id=None,
                correlation_id=None,
                payload={"device_id": device_id},
                aggregate_type="Device",
                aggregate_id=device_id,
            )
        )

        async with self._new_uow() as uow:
            reloaded = await uow.devices.get(DeviceId(device_id))
        self.assertFalse(reloaded.is_online)

    async def test_count_online_reflects_real_seeded_rows(self) -> None:
        online_id = await self._seed_device()
        offline_id = await self._seed_device()
        container = self._make_container_with_real_uow()
        await DeviceConnectivityProcessor("DeviceOnline", container).process(
            DomainEvent(
                event_id="evt-1",
                event_type="DeviceOnline",
                version=1,
                occurred_at=datetime.now(timezone.utc),
                org_id=None,
                correlation_id=None,
                payload={"device_id": online_id},
                aggregate_type="Device",
                aggregate_id=online_id,
            )
        )

        async with self._new_uow() as uow:
            total_before = await uow.devices.count_total()
            online_before = await uow.devices.count_online()

        # Both seeded devices count toward the total; only one is online. Compared against a
        # fresh count with both deleted, to stay correct regardless of this shared dev
        # database's other pre-existing rows. Deleting them here (rather than only in
        # asyncTearDown) is what makes the "after" count meaningful — asyncTearDown's own
        # cleanup DELETE is still safe to run afterward (a no-op against already-gone rows).
        async with self.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM devices WHERE id = ANY(:ids)"),
                {"ids": [online_id, offline_id]},
            )
        async with self._new_uow() as uow:
            total_after = await uow.devices.count_total()
            online_after = await uow.devices.count_online()

        self.assertEqual(total_before - total_after, 2)
        self.assertEqual(online_before - online_after, 1)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class PlatformStatsCompositionLiveTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0020: the real, DI-wired `PlatformStatsApplicationService` end-to-end against a real
    database — proves the four-module composition + `HealthCheckService` reuse actually run
    without error, not just that each piece works in isolation."""

    async def asyncSetUp(self) -> None:
        self.settings = get_settings()
        self.container = build_container(self.settings)

    async def asyncTearDown(self) -> None:
        await self.container.resolve(AsyncEngine).dispose()

    async def test_get_platform_stats_runs_end_to_end_against_real_postgres(self) -> None:
        service = self.container.resolve(PlatformStatsApplicationService)
        org_uow = self.container.resolve(OrganizationUnitOfWork)
        iam_uow = self.container.resolve(IamUnitOfWork)
        fleet_device_uow = self.container.resolve(FleetDeviceUnitOfWork)
        billing_uow = self.container.resolve(BillingUnitOfWork)

        stats = await service.get_platform_stats(
            org_uow=org_uow,
            iam_uow=iam_uow,
            fleet_device_uow=fleet_device_uow,
            billing_uow=billing_uow,
        )

        # Structural/type sanity — this sandbox's shared dev database carries arbitrary
        # pre-existing rows from earlier session work, so exact counts aren't meaningful here.
        self.assertGreaterEqual(stats.organizations.total, 0)
        self.assertIsInstance(stats.organizations.by_status, dict)
        self.assertGreaterEqual(stats.users.total, 0)
        self.assertGreaterEqual(stats.users.monthly_active, 0)
        self.assertGreaterEqual(stats.vehicles.total, 0)
        self.assertEqual(stats.devices.total, stats.devices.online + stats.devices.offline)
        self.assertIsInstance(stats.billing.revenue, float)
        # Postgres is genuinely reachable in this sandbox — confirmed throughout this session.
        self.assertEqual(stats.system_health.database, "ok")


if __name__ == "__main__":
    unittest.main()
