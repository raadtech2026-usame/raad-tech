"""PostgreSQL-backed integration tests for the safety-critical, database-level invariants that
no pure in-memory unit test can actually prove: partial unique indexes, global uniqueness
constraints, and optimistic-locking (`row_version`) behavior. Stdlib `unittest` — no `pytest`
(not an approved dependency), using `unittest.IsolatedAsyncioTestCase` against the real
`SqlAlchemyUnitOfWork`/repositories and the live migrated schema (Alembic head
`ed48df51b591`), not fakes.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`, per
`ADR-0002`). Every test inserts rows tagged with a unique per-run marker and deletes them in
`tearDown`, so the suite never touches real data and leaves the schema exactly as found — no
new tables, no Alembic migration involved, matching every prior phase's live-verification
pattern in this project's history. If no database is configured, every test is skipped rather
than failing the whole run (`core/di`'s own "fail loudly only when actually attempting to use
it" posture) — this suite still needs to be *run* deliberately in an environment with
PostgreSQL reachable to actually exercise these invariants.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

import sqlalchemy.exc
from sqlalchemy.orm.exc import StaleDataError

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.modules.fleet_device.domain.entities import Device, DeviceAssignment, Vehicle
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    DeviceId,
    DeviceLifecycleState,
    OrganizationId as FleetOrganizationId,
    TerminalId,
    VehicleId,
    VehicleStatus,
)
from raad.modules.fleet_device.infra.repositories import SqlAlchemyFleetDeviceUnitOfWork
from raad.modules.iam.domain.entities import User
from raad.modules.iam.domain.value_objects import Email, UserId, UserStatus
from raad.modules.iam.infra.models import UserModel
from raad.modules.iam.infra.repositories import SqlAlchemyIamUnitOfWork
from raad.core.tenancy.principal import Role
from raad.core.time.clock import SystemClock


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class FleetDeviceAssignmentDatabaseInvariantTests(unittest.IsolatedAsyncioTestCase):
    """The flagship safety-critical invariant, proven at the actual database layer this time
    (not a faithful fake, the real `ux_device_assignments__active_device`/`__active_vehicle`
    partial unique indexes, ADR-0002)."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: dict[str, list[str]] = {
            "device_assignments": [],
            "devices": [],
            "vehicles": [],
        }

    async def asyncTearDown(self) -> None:
        # Clean up in FK-safe order: assignments -> devices/vehicles.
        async with self.engine.begin() as conn:
            from sqlalchemy import text

            if self._created_ids["device_assignments"]:
                await conn.execute(
                    text("DELETE FROM device_assignments WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids["device_assignments"]},
                )
            if self._created_ids["devices"]:
                await conn.execute(
                    text("DELETE FROM devices WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids["devices"]},
                )
            if self._created_ids["vehicles"]:
                await conn.execute(
                    text("DELETE FROM vehicles WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids["vehicles"]},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyFleetDeviceUnitOfWork:
        return SqlAlchemyFleetDeviceUnitOfWork(self.session_factory, self.outbox_writer)

    async def _seed_vehicle_and_devices(self, org_id: str):
        async with self._new_uow() as uow:
            vehicle = Vehicle.register(
                id=VehicleId(self.id_generator.new_id()),
                organization_id=FleetOrganizationId(org_id),
                plate_no=f"TEST-{self.tag}",
                clock=self.clock,
            )
            device_a = Device.register(
                id=DeviceId(self.id_generator.new_id()),
                organization_id=FleetOrganizationId(org_id),
                terminal_id=TerminalId(f"TERM-{self.tag}-A"),
                clock=self.clock,
            )
            device_b = Device.register(
                id=DeviceId(self.id_generator.new_id()),
                organization_id=FleetOrganizationId(org_id),
                terminal_id=TerminalId(f"TERM-{self.tag}-B"),
                clock=self.clock,
            )
            uow.vehicles.add(vehicle)
            uow.devices.add(device_a)
            uow.devices.add(device_b)
            uow.record_events(vehicle.pull_domain_events())
            uow.record_events(device_a.pull_domain_events())
            uow.record_events(device_b.pull_domain_events())
            await uow.commit()
            self._created_ids["vehicles"].append(str(vehicle.id))
            self._created_ids["devices"].append(str(device_a.id))
            self._created_ids["devices"].append(str(device_b.id))
            return vehicle.id, device_a.id, device_b.id

    async def test_two_active_assignments_for_the_same_vehicle_violate_db_constraint(
        self,
    ) -> None:
        """Regression, at the database layer: `ux_device_assignments__active_vehicle`
        (partial unique index, WHERE unassigned_at IS NULL) rejects a second active binding
        for the same vehicle even if the application-layer guard were somehow bypassed.
        """
        org_id = f"org-{self.tag}"
        vehicle_id, device_a_id, device_b_id = await self._seed_vehicle_and_devices(
            org_id
        )

        async with self._new_uow() as uow:
            first = DeviceAssignment.open(
                id=AssignmentId(self.id_generator.new_id()),
                organization_id=FleetOrganizationId(org_id),
                device_id=device_a_id,
                vehicle_id=vehicle_id,
                clock=self.clock,
            )
            uow.device_assignments.add(first)
            await uow.commit()
            self._created_ids["device_assignments"].append(str(first.id))

        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            async with self._new_uow() as uow:
                second = DeviceAssignment.open(
                    id=AssignmentId(self.id_generator.new_id()),
                    organization_id=FleetOrganizationId(org_id),
                    device_id=device_b_id,
                    vehicle_id=vehicle_id,  # same vehicle, still active -> DB rejects
                    clock=self.clock,
                )
                uow.device_assignments.add(second)
                await uow.commit()
                self._created_ids["device_assignments"].append(str(second.id))


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class IamDatabaseInvariantTests(unittest.IsolatedAsyncioTestCase):
    """Global email uniqueness (Database Design §4.3) and optimistic locking (`row_version`),
    proven against the real `users` table."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        from sqlalchemy import text

        async with self.engine.begin() as conn:
            if self._created_ids:
                await conn.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyIamUnitOfWork:
        return SqlAlchemyIamUnitOfWork(self.session_factory, self.outbox_writer)

    async def test_duplicate_email_violates_db_unique_constraint(self) -> None:
        """Regression, at the database layer: `ux_users__email` rejects a second user with the
        same email even if the application-layer `ensure_email_available` check were somehow
        bypassed (e.g. a race between two concurrent requests)."""
        email = f"dbtest-{self.tag}@example.com"

        async with self._new_uow() as uow:
            first = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=None,
                role=Role.FOUNDER,
                email=Email(email),
                phone=None,
                full_name="First",
                clock=self.clock,
            )
            uow.users.add(first)
            uow.record_events(first.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(first.id))

        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            async with self._new_uow() as uow:
                second = User.invite(
                    id=UserId(self.id_generator.new_id()),
                    organization_id=None,
                    role=Role.FOUNDER,
                    email=Email(email),  # same email -> DB rejects
                    phone=None,
                    full_name="Second",
                    clock=self.clock,
                )
                uow.users.add(second)
                uow.record_events(second.pull_domain_events())
                await uow.commit()
                self._created_ids.append(str(second.id))

    async def test_concurrent_update_raises_stale_data_error(self) -> None:
        """Regression: optimistic concurrency via `row_version` (`AuditActorMixin`,
        `core/db/mixins.py`) - two independently-loaded copies of the same row, both mutated,
        the second commit must fail rather than silently overwrite the first."""
        email = f"concurrent-{self.tag}@example.com"

        async with self._new_uow() as uow:
            user = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=None,
                role=Role.FOUNDER,
                email=Email(email),
                phone=None,
                full_name="Original Name",
                clock=self.clock,
            )
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            user_id = user.id
            self._created_ids.append(str(user_id))

        # `uow_2`'s session loads the row FIRST (capturing row_version=1) and stays open
        # across `uow_1`'s entire, independent load-mutate-commit cycle (nested inside), which
        # bumps the row to version=2 in the database. `uow_2` then mutates its own
        # already-loaded (now-stale) copy and commits - a true concurrent-edit simulation, not
        # a sequential one. Each side applies a genuine state *change* (INVITED -> ACTIVE vs.
        # INVITED -> DISABLED), not an idempotent no-op, so both attempt a real
        # version-checked UPDATE.
        uow_2 = self._new_uow()
        async with uow_2:
            copy_2 = await uow_2.users.get(user_id)

            async with self._new_uow() as uow_1:
                copy_1 = await uow_1.users.get(user_id)
                copy_1.activate(clock=self.clock)
                uow_1.record_events(copy_1.pull_domain_events())
                await uow_1.commit()  # succeeds, row_version 1 -> 2

            with self.assertRaises(StaleDataError):
                copy_2.disable(clock=self.clock)
                uow_2.record_events(copy_2.pull_domain_events())
                await uow_2.commit()  # still thinks row_version=1 -> must fail, not overwrite


if __name__ == "__main__":
    unittest.main()
