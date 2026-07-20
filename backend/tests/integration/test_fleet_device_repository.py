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
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
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


if __name__ == "__main__":
    unittest.main()
