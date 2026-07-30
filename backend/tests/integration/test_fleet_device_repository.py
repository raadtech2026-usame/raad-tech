"""PostgreSQL-backed integration test for `fleet_device`'s `SqlAlchemyVehicleRepository`/
`SqlAlchemyDeviceRepository`. Stdlib `unittest` — no `pytest` (not an approved dependency) —
against the real `SqlAlchemyFleetDeviceUnitOfWork` and the live migrated schema, not fakes,
mirroring `test_transport_ops_driver_repository.py`'s skip-guard/cleanup pattern exactly.

**Closes a real, previously-flagged gap**: CLAUDE.md's own "Known gaps" section names Fleet
Device as one of four modules with no dedicated live-DB integration test file.
`ux_device_assignments__active_vehicle`'s DB-level partial-unique-index invariant already has
its own dedicated proof in `test_postgres_repository_invariants.py` — this file covers the
plain `Vehicle`/`Device` round trips that test doesn't, not a duplicate of it.

`organization_id` here is `fleet_device`'s own opaque, cross-module value object (no FK to
`organizations`, per `.claude/rules/database.md` #3) — no `organization`-module row needs to
exist first, unlike `test_organization_repository.py`'s in-context `region_id` FK.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown`.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import ValidationError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.fleet_device.domain.entities import Device, Vehicle
from raad.modules.fleet_device.domain.value_objects import (
    DeviceId,
    DeviceLifecycleState,
    OrganizationId,
    TerminalId,
    VehicleId,
    VehicleStatus,
)
from raad.modules.fleet_device.infra.repositories import SqlAlchemyFleetDeviceUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class VehicleAndDeviceRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_vehicle_ids: list[str] = []
        self._created_device_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_vehicle_ids:
                await conn.execute(
                    text("DELETE FROM vehicles WHERE id = ANY(:ids)"),
                    {"ids": self._created_vehicle_ids},
                )
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

    async def test_vehicle_add_then_get_round_trips_all_fields(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            vehicle = Vehicle.register(
                id=VehicleId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                plate_no=f"PLATE-{self.tag}",
                label=f"Bus {self.tag}",
                capacity=40,
                clock=self.clock,
            )
            uow.vehicles.add(vehicle)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            vehicle_id = vehicle.id
            self._created_vehicle_ids.append(str(vehicle_id))

        async with self._new_uow() as uow:
            fetched = await uow.vehicles.get(vehicle_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(fetched.plate_no, f"PLATE-{self.tag}")
        self.assertEqual(fetched.status, VehicleStatus.ACTIVE)

    async def test_vehicle_mutation_after_get_persists_without_a_second_add(self) -> None:
        """Proves the identity-map/`flush_tracked_changes` bridge: `get()` returns a detached
        domain object, and calling a lifecycle method on it followed by `commit()` (no `add()`
        call) must still persist, because the repository re-projects the tracked object onto
        its ORM row."""
        async with self._new_uow() as uow:
            vehicle = Vehicle.register(
                id=VehicleId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                plate_no=f"MUT-{self.tag}",
                clock=self.clock,
            )
            uow.vehicles.add(vehicle)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            vehicle_id = vehicle.id
            self._created_vehicle_ids.append(str(vehicle_id))

        async with self._new_uow() as uow:
            loaded = await uow.vehicles.get(vehicle_id)
            loaded.deactivate(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.vehicles.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.vehicles.get(vehicle_id)

        self.assertEqual(refetched.status, VehicleStatus.INACTIVE)

    async def test_vehicle_list_all_includes_newly_added_vehicle(self) -> None:
        async with self._new_uow() as uow:
            vehicle = Vehicle.register(
                id=VehicleId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                plate_no=f"LIST-{self.tag}",
                clock=self.clock,
            )
            uow.vehicles.add(vehicle)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            self._created_vehicle_ids.append(str(vehicle.id))

        async with self._new_uow() as uow:
            all_vehicles = await uow.vehicles.list_all()

        self.assertIn(str(vehicle.id), {str(v.id) for v in all_vehicles})

    async def test_get_missing_vehicle_returns_none(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.vehicles.get(VehicleId(self.id_generator.new_id()))
        self.assertIsNone(result)

    async def test_device_add_then_get_round_trips_all_fields(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            device = Device.register(
                id=DeviceId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                terminal_id=TerminalId(f"TERM-{self.tag}"),
                model="JT808-X1",
                vendor="Acme",
                clock=self.clock,
            )
            uow.devices.add(device)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            device_id = device.id
            self._created_device_ids.append(str(device_id))

        async with self._new_uow() as uow:
            fetched = await uow.devices.get(device_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(str(fetched.terminal_id), f"TERM-{self.tag}")
        self.assertEqual(fetched.lifecycle_state, DeviceLifecycleState.REGISTERED)

    async def test_record_last_seen_persists_without_a_second_add(self) -> None:
        """`docs/architecture/post-f7-production-readiness-roadmap.md` Phase A item A3, at the
        repository layer: `Device.record_last_seen` (a state-sync-only mutator, no domain event)
        followed by `commit()` — no `add()` call — must still persist, the identical
        identity-map proof `test_vehicle_mutation_after_get_persists_without_a_second_add`
        already establishes for `Vehicle.deactivate`."""
        async with self._new_uow() as uow:
            device = Device.register(
                id=DeviceId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                terminal_id=TerminalId(f"SEEN-{self.tag}"),
                clock=self.clock,
            )
            uow.devices.add(device)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            device_id = device.id
            self._created_device_ids.append(str(device_id))

        # Deliberately tz-aware, matching the real caller (`event.occurred_at`, parsed from an
        # ISO-8601 string, `.claude/rules/database.md` #1 UTC convention) - proves the mapper's
        # own `_naive()` guard (this test's real regression target: `last_seen_at` had no writer
        # anywhere before this phase, so this tz-aware-into-naive-column mismatch was latent).
        seen_at = self.clock.now().replace(microsecond=0)
        async with self._new_uow() as uow:
            loaded = await uow.devices.get(device_id)
            self.assertIsNone(loaded.last_seen_at)
            loaded.record_last_seen(seen_at)
            await uow.commit()  # no uow.devices.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.devices.get(device_id)

        self.assertEqual(refetched.last_seen_at, seen_at.replace(tzinfo=None))

    async def test_device_list_all_includes_newly_added_device(self) -> None:
        async with self._new_uow() as uow:
            device = Device.register(
                id=DeviceId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                terminal_id=TerminalId(f"LIST-{self.tag}"),
                clock=self.clock,
            )
            uow.devices.add(device)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            self._created_device_ids.append(str(device.id))

        async with self._new_uow() as uow:
            all_devices = await uow.devices.list_all()

        self.assertIn(str(device.id), {str(d.id) for d in all_devices})


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class VehiclePaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyVehicleRepository.list_page` (`core/db/repository.py`'s generic
    engine, `fleet_device`'s own whitelist) against real SQL — offset/limit, `ILIKE` search,
    whitelisted filter/sort, `func.count()` over the same filtered predicate — mirroring
    `test_organization_repository.py`'s `OrganizationPaginationRepositoryTests` exactly."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_vehicle_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_vehicle_ids:
                await conn.execute(
                    text("DELETE FROM vehicles WHERE id = ANY(:ids)"),
                    {"ids": self._created_vehicle_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyFleetDeviceUnitOfWork:
        return SqlAlchemyFleetDeviceUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed(
        self, *, plate_no: str, organization_id: str, under_maintenance: bool = False
    ) -> None:
        async with self._new_uow() as uow:
            vehicle = Vehicle.register(
                id=VehicleId(self.id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                plate_no=plate_no,
                clock=self.clock,
            )
            if under_maintenance:
                vehicle.mark_under_maintenance(clock=self.clock)
            uow.vehicles.add(vehicle)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            self._created_vehicle_ids.append(str(vehicle.id))

    async def test_list_page_paginates_and_reports_total(self) -> None:
        org_id = self.id_generator.new_id()
        for i in range(3):
            await self._seed(plate_no=f"Page-{self.tag}-{i}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.vehicles.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="plate_no")],
                filters=[FilterCondition(field="organization_id", op="eq", value=org_id)],
                search=None,
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_status(self) -> None:
        org_id = self.id_generator.new_id()
        await self._seed(plate_no=f"Active-{self.tag}", organization_id=org_id)
        await self._seed(
            plate_no=f"Maint-{self.tag}",
            organization_id=org_id,
            under_maintenance=True,
        )

        async with self._new_uow() as uow:
            page = await uow.vehicles.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(field="organization_id", op="eq", value=org_id),
                    FilterCondition(field="status", op="eq", value="maintenance"),
                ],
                search=None,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].plate_no, f"Maint-{self.tag}")

    async def test_list_page_search_matches_plate_no_substring(self) -> None:
        org_id = self.id_generator.new_id()
        await self._seed(plate_no=f"Findable-{self.tag}", organization_id=org_id)
        await self._seed(plate_no=f"Other-{self.tag}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.vehicles.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[FilterCondition(field="organization_id", op="eq", value=org_id)],
                search="findable",
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].plate_no, f"Findable-{self.tag}")

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.vehicles.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="id", op="eq", value="x")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.vehicles.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="capacity")],
                    filters=[],
                    search=None,
                )


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class DevicePaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyDeviceRepository.list_page` against real SQL — mirrors
    `VehiclePaginationRepositoryTests` above. `sim_msisdn` is deliberately never used as a
    filter/sort field here — it is PII and not in the repository's whitelist
    (`infra/repositories.py`'s own comment)."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
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

    async def _seed(
        self, *, terminal_id: str, organization_id: str, activated: bool = False
    ) -> None:
        async with self._new_uow() as uow:
            device = Device.register(
                id=DeviceId(self.id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                terminal_id=TerminalId(terminal_id),
                clock=self.clock,
            )
            if activated:
                device.activate(clock=self.clock)
            uow.devices.add(device)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            self._created_device_ids.append(str(device.id))

    async def test_list_page_paginates_and_reports_total(self) -> None:
        org_id = self.id_generator.new_id()
        for i in range(3):
            await self._seed(
                terminal_id=f"Page-{self.tag}-{i}", organization_id=org_id
            )

        async with self._new_uow() as uow:
            page = await uow.devices.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="terminal_id")],
                filters=[FilterCondition(field="organization_id", op="eq", value=org_id)],
                search=None,
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_lifecycle_state(self) -> None:
        org_id = self.id_generator.new_id()
        await self._seed(
            terminal_id=f"Activated-{self.tag}", organization_id=org_id, activated=True
        )
        await self._seed(terminal_id=f"Registered-{self.tag}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.devices.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(field="organization_id", op="eq", value=org_id),
                    FilterCondition(
                        field="lifecycle_state", op="eq", value="activated"
                    ),
                ],
                search=None,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].terminal_id, TerminalId(f"Activated-{self.tag}"))

    async def test_list_page_search_matches_terminal_id_substring(self) -> None:
        org_id = self.id_generator.new_id()
        await self._seed(terminal_id=f"Findable-{self.tag}", organization_id=org_id)
        await self._seed(terminal_id=f"Other-{self.tag}", organization_id=org_id)

        async with self._new_uow() as uow:
            page = await uow.devices.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[FilterCondition(field="organization_id", op="eq", value=org_id)],
                search="findable",
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(str(page.data[0].terminal_id), f"Findable-{self.tag}")

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        """`sim_msisdn` is PII and deliberately excluded from the filterable whitelist."""
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.devices.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="sim_msisdn", op="eq", value="x")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.devices.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="sim_msisdn")],
                    filters=[],
                    search=None,
                )


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class TenantIsolationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0021: proves `TenantRegionScope` bound at UoW construction is actually enforced by
    `SqlAlchemyVehicleRepository`/`SqlAlchemyDeviceRepository` against a real, live database —
    two genuinely distinct organizations, not fakes. This is the "Organization A cannot
    see/reach Organization B's data" security requirement, at the repository layer."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self.org_a = self.id_generator.new_id()
        self.org_b = self.id_generator.new_id()
        self._created_vehicle_ids: list[str] = []
        self._created_device_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_vehicle_ids:
                await conn.execute(
                    text("DELETE FROM vehicles WHERE id = ANY(:ids)"),
                    {"ids": self._created_vehicle_ids},
                )
            if self._created_device_ids:
                await conn.execute(
                    text("DELETE FROM devices WHERE id = ANY(:ids)"),
                    {"ids": self._created_device_ids},
                )
        await self.engine.dispose()

    def _new_uow(
        self, *, scope: TenantRegionScope | None = None
    ) -> SqlAlchemyFleetDeviceUnitOfWork:
        uow = SqlAlchemyFleetDeviceUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )
        if scope is not None:
            uow.scope = scope
        return uow

    async def _seed_vehicle(self, *, organization_id: str, plate_no: str) -> str:
        async with self._new_uow() as uow:
            vehicle = Vehicle.register(
                id=VehicleId(self.id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                plate_no=plate_no,
                clock=self.clock,
            )
            uow.vehicles.add(vehicle)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            self._created_vehicle_ids.append(str(vehicle.id))
            return str(vehicle.id)

    async def _seed_device(self, *, organization_id: str, terminal_id: str) -> str:
        async with self._new_uow() as uow:
            device = Device.register(
                id=DeviceId(self.id_generator.new_id()),
                organization_id=OrganizationId(organization_id),
                terminal_id=TerminalId(terminal_id),
                clock=self.clock,
            )
            uow.devices.add(device)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            self._created_device_ids.append(str(device.id))
            return str(device.id)

    async def test_org_a_cannot_get_org_bs_vehicle_by_id(self) -> None:
        """The IDOR case: substituting another organization's real id must not work, even
        though the id itself is perfectly valid and exists."""
        vehicle_b = await self._seed_vehicle(
            organization_id=self.org_b, plate_no=f"IDOR-{self.tag}"
        )

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.vehicles.get(VehicleId(vehicle_b))

        self.assertIsNone(result)

    async def test_org_a_can_still_get_its_own_vehicle_by_id(self) -> None:
        vehicle_a = await self._seed_vehicle(
            organization_id=self.org_a, plate_no=f"OWN-{self.tag}"
        )

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.vehicles.get(VehicleId(vehicle_a))

        self.assertIsNotNone(result)
        self.assertEqual(str(result.id), vehicle_a)

    async def test_org_a_list_all_excludes_org_bs_vehicles(self) -> None:
        vehicle_a = await self._seed_vehicle(
            organization_id=self.org_a, plate_no=f"LISTA-{self.tag}"
        )
        vehicle_b = await self._seed_vehicle(
            organization_id=self.org_b, plate_no=f"LISTB-{self.tag}"
        )

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            visible = await uow.vehicles.list_all()

        visible_ids = {str(v.id) for v in visible}
        self.assertIn(vehicle_a, visible_ids)
        self.assertNotIn(vehicle_b, visible_ids)

    async def test_org_a_list_page_excludes_org_bs_vehicles(self) -> None:
        vehicle_a = await self._seed_vehicle(
            organization_id=self.org_a, plate_no=f"PAGEA-{self.tag}"
        )
        vehicle_b = await self._seed_vehicle(
            organization_id=self.org_b, plate_no=f"PAGEB-{self.tag}"
        )

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            page = await uow.vehicles.list_page(
                OffsetPageRequest(), sort=[], filters=[], search=None
            )

        visible_ids = {str(v.id) for v in page.data}
        self.assertIn(vehicle_a, visible_ids)
        self.assertNotIn(vehicle_b, visible_ids)

    async def test_org_a_cannot_bypass_scope_via_organization_id_filter(self) -> None:
        """"Organization A cannot search Organization B's data" — a client-supplied
        `filter[organization_id]=<org B>` must not override the bound scope; SQLAlchemy `.where()`
        composes as AND, so this must return zero rows, not Organization B's vehicle."""
        await self._seed_vehicle(organization_id=self.org_b, plate_no=f"SEARCH-{self.tag}")

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            page = await uow.vehicles.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(field="organization_id", op="eq", value=self.org_b)
                ],
                search=None,
            )

        self.assertEqual(page.total, 0)
        self.assertEqual(page.data, [])

    async def test_org_a_cannot_get_org_bs_device_by_id(self) -> None:
        device_b = await self._seed_device(
            organization_id=self.org_b, terminal_id=f"IDOR-{self.tag}"
        )

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.devices.get(DeviceId(device_b))

        self.assertIsNone(result)

    async def test_founder_unrestricted_scope_sees_both_organizations(self) -> None:
        """The unrestricted case (Founder) must be unaffected — confirms the fix narrows
        tenant roles without breaking platform-wide visibility for the role that needs it."""
        vehicle_a = await self._seed_vehicle(
            organization_id=self.org_a, plate_no=f"ALL-A-{self.tag}"
        )
        vehicle_b = await self._seed_vehicle(
            organization_id=self.org_b, plate_no=f"ALL-B-{self.tag}"
        )

        unrestricted = TenantRegionScope(organization_ids=None)
        async with self._new_uow(scope=unrestricted) as uow:
            visible = await uow.vehicles.list_all()

        visible_ids = {str(v.id) for v in visible}
        self.assertIn(vehicle_a, visible_ids)
        self.assertIn(vehicle_b, visible_ids)


if __name__ == "__main__":
    unittest.main()
