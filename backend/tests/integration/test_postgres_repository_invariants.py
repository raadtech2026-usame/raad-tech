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
from datetime import date, datetime, timezone

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
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Route,
    Student,
    StudentAssignment,
    Trip,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    OrganizationId as TransportOpsOrganizationId,
    RouteId,
    StopId,
    StudentAssignmentId,
    StudentId,
    TripId,
    TripType,
    UserId as TransportOpsUserId,
    VehicleId,
)
from raad.modules.transport_ops.infra.repositories import (
    SqlAlchemyTransportOpsUnitOfWork,
)
from raad.modules.billing.domain.entities import Invoice, Payment, Plan, Subscription
from raad.modules.billing.domain.value_objects import (
    BillingCycle,
    BillingScope,
    InvoiceId,
    Money,
    OrganizationId as BillingOrganizationId,
    PaymentId,
    PlanId,
    SubscriberId,
    SubscriberType,
    SubscriptionId,
)
from raad.modules.billing.infra.repositories import SqlAlchemyBillingUnitOfWork


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
class TripDatabaseInvariantTests(unittest.IsolatedAsyncioTestCase):
    """One-active-trip-per-vehicle (Phase 12, Database Design §6.8), proven at the actual
    database layer — the real `ux_trips__active_vehicle` partial unique index (`WHERE
    status = 'in_progress'`), the same category of proof
    `FleetDeviceAssignmentDatabaseInvariantTests` above already gives
    `ux_device_assignments__active_vehicle`."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: dict[str, list[str]] = {
            "trips": [],
            "drivers": [],
            "routes": [],
        }

    async def asyncTearDown(self) -> None:
        from sqlalchemy import text

        async with self.engine.begin() as conn:
            if self._created_ids["trips"]:
                await conn.execute(
                    text("DELETE FROM trips WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids["trips"]},
                )
            if self._created_ids["drivers"]:
                await conn.execute(
                    text("DELETE FROM drivers WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids["drivers"]},
                )
            if self._created_ids["routes"]:
                await conn.execute(
                    text("DELETE FROM routes WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids["routes"]},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(self.session_factory, self.outbox_writer)

    async def _seed_driver_and_route(self, org_id: str):
        async with self._new_uow() as uow:
            driver = Driver.register(
                id=DriverId(self.id_generator.new_id()),
                organization_id=TransportOpsOrganizationId(org_id),
                user_id=TransportOpsUserId(self.id_generator.new_id()),
                license_no=f"LIC-{self.tag}",
                clock=self.clock,
            )
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=TransportOpsOrganizationId(org_id),
                name=f"Route {self.tag}",
                clock=self.clock,
            )
            uow.drivers.add(driver)
            uow.routes.add(route)
            uow.record_events(driver.pull_domain_events())
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            self._created_ids["drivers"].append(str(driver.id))
            self._created_ids["routes"].append(str(route.id))
            return driver.id, route.id

    async def test_two_in_progress_trips_for_the_same_vehicle_violate_db_constraint(
        self,
    ) -> None:
        """Regression, at the database layer: `ux_trips__active_vehicle` (partial unique
        index, WHERE status = 'in_progress') rejects a second in-progress trip for the same
        vehicle even if the application-layer `ensure_vehicle_has_no_active_trip` guard were
        somehow bypassed (e.g. a race between two concurrent requests)."""
        org_id = f"org-{self.tag}"
        driver_id, route_id = await self._seed_driver_and_route(org_id)
        vehicle_id = VehicleId(self.id_generator.new_id())

        async with self._new_uow() as uow:
            first = Trip.schedule(
                id=TripId(self.id_generator.new_id()),
                organization_id=TransportOpsOrganizationId(org_id),
                vehicle_id=vehicle_id,
                driver_id=driver_id,
                driver_organization_id=TransportOpsOrganizationId(org_id),
                route_id=route_id,
                route_organization_id=TransportOpsOrganizationId(org_id),
                trip_type=TripType.MORNING,
                scheduled_date=date(2026, 7, 20),
                clock=self.clock,
            )
            first.start(clock=self.clock)
            uow.trips.add(first)
            uow.record_events(first.pull_domain_events())
            await uow.commit()
            self._created_ids["trips"].append(str(first.id))

        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            async with self._new_uow() as uow:
                second = Trip.schedule(
                    id=TripId(self.id_generator.new_id()),
                    organization_id=TransportOpsOrganizationId(org_id),
                    vehicle_id=vehicle_id,  # same vehicle, still in_progress -> DB rejects
                    driver_id=driver_id,
                    driver_organization_id=TransportOpsOrganizationId(org_id),
                    route_id=route_id,
                    route_organization_id=TransportOpsOrganizationId(org_id),
                    trip_type=TripType.AFTERNOON,
                    scheduled_date=date(2026, 7, 20),
                    clock=self.clock,
                )
                second.start(clock=self.clock)
                uow.trips.add(second)
                uow.record_events(second.pull_domain_events())
                await uow.commit()
                self._created_ids["trips"].append(str(second.id))


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class StudentAssignmentDatabaseInvariantTests(unittest.IsolatedAsyncioTestCase):
    """One-active-assignment-per-student (Phase 13, Database Design §6.7), proven at the actual
    database layer — the real `ux_student_assignments__active_student` partial unique index
    (`WHERE status = 'active'`), the same category of proof `TripDatabaseInvariantTests` above
    already gives `ux_trips__active_vehicle`."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: dict[str, list[str]] = {
            "student_assignments": [],
            "students": [],
            "routes": [],
        }

    async def asyncTearDown(self) -> None:
        from sqlalchemy import text

        async with self.engine.begin() as conn:
            if self._created_ids["student_assignments"]:
                await conn.execute(
                    text("DELETE FROM student_assignments WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids["student_assignments"]},
                )
            if self._created_ids["students"]:
                await conn.execute(
                    text("DELETE FROM students WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids["students"]},
                )
            if self._created_ids["routes"]:
                await conn.execute(
                    text("DELETE FROM stops WHERE route_id = ANY(:ids)"),
                    {"ids": self._created_ids["routes"]},
                )
                await conn.execute(
                    text("DELETE FROM routes WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids["routes"]},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(self.session_factory, self.outbox_writer)

    async def _seed_student_and_route(self, org_id: str):
        async with self._new_uow() as uow:
            student = Student.enroll(
                id=StudentId(self.id_generator.new_id()),
                organization_id=TransportOpsOrganizationId(org_id),
                full_name=f"Student {self.tag}",
                clock=self.clock,
            )
            route = Route.create(
                id=RouteId(self.id_generator.new_id()),
                organization_id=TransportOpsOrganizationId(org_id),
                name=f"Route {self.tag}",
                clock=self.clock,
            )
            pickup = route.add_stop(
                id=StopId(self.id_generator.new_id()),
                name="Pickup",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                clock=self.clock,
            )
            dropoff = route.add_stop(
                id=StopId(self.id_generator.new_id()),
                name="Dropoff",
                latitude=2.6,
                longitude=45.4,
                sequence_no=2,
                clock=self.clock,
            )
            uow.students.add(student)
            uow.routes.add(route)
            uow.record_events(student.pull_domain_events())
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            self._created_ids["students"].append(str(student.id))
            self._created_ids["routes"].append(str(route.id))
            return student.id, route.id, pickup.id, dropoff.id

    async def test_two_active_assignments_for_the_same_student_violate_db_constraint(
        self,
    ) -> None:
        """Regression, at the database layer: `ux_student_assignments__active_student` (partial
        unique index, WHERE status = 'active') rejects a second active assignment for the same
        student even if the application-layer `ensure_student_has_no_active_assignment` guard
        were somehow bypassed (e.g. a race between two concurrent requests)."""
        org_id = f"org-{self.tag}"
        student_id, route_id, pickup_id, dropoff_id = await self._seed_student_and_route(
            org_id
        )

        async with self._new_uow() as uow:
            first = StudentAssignment.assign(
                id=StudentAssignmentId(self.id_generator.new_id()),
                organization_id=TransportOpsOrganizationId(org_id),
                student_id=student_id,
                student_organization_id=TransportOpsOrganizationId(org_id),
                route_id=route_id,
                route_organization_id=TransportOpsOrganizationId(org_id),
                pickup_stop_id=pickup_id,
                dropoff_stop_id=dropoff_id,
                vehicle_id=None,
                clock=self.clock,
            )
            uow.student_assignments.add(first)
            uow.record_events(first.pull_domain_events())
            await uow.commit()
            self._created_ids["student_assignments"].append(str(first.id))

        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            async with self._new_uow() as uow:
                second = StudentAssignment.assign(
                    id=StudentAssignmentId(self.id_generator.new_id()),
                    organization_id=TransportOpsOrganizationId(org_id),
                    student_id=student_id,  # same student, still active -> DB rejects
                    student_organization_id=TransportOpsOrganizationId(org_id),
                    route_id=route_id,
                    route_organization_id=TransportOpsOrganizationId(org_id),
                    pickup_stop_id=pickup_id,
                    dropoff_stop_id=dropoff_id,
                    vehicle_id=None,
                    clock=self.clock,
                )
                uow.student_assignments.add(second)
                uow.record_events(second.pull_domain_events())
                await uow.commit()
                self._created_ids["student_assignments"].append(str(second.id))


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


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class BillingDatabaseInvariantTests(unittest.IsolatedAsyncioTestCase):
    """Phase 15: the two global-uniqueness constraints Database Design §8.3/§8.4 document for
    `billing` (`ux_invoices__number`, `ux_payments__idempotency_key`), proven at the real
    database layer — defense-in-depth over `PaymentRepository.get_by_idempotency_key`'s
    application-level find-or-return check (`application/validators.py`'s own docstring: no
    `ensure_idempotency_key_available` guard exists precisely because idempotency is
    "return the original," not "reject the duplicate" — this DB constraint is what actually
    stops two *independently minted* `Payment` rows from ever sharing a key, e.g. a
    non-idempotent caller bug). No partial-unique index exists for any billing table
    (`infra/models.py`'s own module docstring — no "one active X" invariant is documented for
    `billing`), so unlike the `Trip`/`StudentAssignment`/`DeviceAssignment` classes above, there
    is nothing analogous to prove here.
    """

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_payment_ids: list[str] = []
        self._created_invoice_ids: list[str] = []
        self._created_subscription_ids: list[str] = []
        self._created_plan_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        from sqlalchemy import text

        async with self.engine.begin() as conn:
            if self._created_payment_ids:
                await conn.execute(
                    text("DELETE FROM payments WHERE id = ANY(:ids)"),
                    {"ids": self._created_payment_ids},
                )
            if self._created_invoice_ids:
                await conn.execute(
                    text("DELETE FROM invoices WHERE id = ANY(:ids)"),
                    {"ids": self._created_invoice_ids},
                )
            if self._created_subscription_ids:
                await conn.execute(
                    text("DELETE FROM subscriptions WHERE id = ANY(:ids)"),
                    {"ids": self._created_subscription_ids},
                )
            if self._created_plan_ids:
                await conn.execute(
                    text("DELETE FROM plans WHERE id = ANY(:ids)"),
                    {"ids": self._created_plan_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyBillingUnitOfWork:
        return SqlAlchemyBillingUnitOfWork(self.session_factory, self.outbox_writer)

    async def _seed_invoice(self) -> Invoice:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            plan = Plan.create(
                id=PlanId(self.id_generator.new_id()),
                name=f"Plan {self.tag}",
                billing_scope=BillingScope.PARENT,
                price=Money(15.00, "USD"),
                billing_cycle=BillingCycle.MONTHLY,
                clock=self.clock,
            )
            uow.plans.add(plan)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
            self._created_plan_ids.append(str(plan.id))

        async with self._new_uow() as uow:
            subscription = Subscription.open(
                id=SubscriptionId(self.id_generator.new_id()),
                organization_id=BillingOrganizationId(org_id),
                subscriber_type=SubscriberType.PARENT,
                subscriber_id=SubscriberId(self.id_generator.new_id()),
                plan_id=plan.id,
                clock=self.clock,
            )
            uow.subscriptions.add(subscription)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
            self._created_subscription_ids.append(str(subscription.id))

        async with self._new_uow() as uow:
            invoice = Invoice.issue(
                id=InvoiceId(self.id_generator.new_id()),
                organization_id=BillingOrganizationId(org_id),
                subscription_id=subscription.id,
                amount=Money(15.00, "USD"),
                period_start=date(2026, 7, 20),
                period_end=date(2026, 8, 19),
                due_at=None,
                clock=self.clock,
            )
            uow.invoices.add(invoice)
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            self._created_invoice_ids.append(str(invoice.id))
        return invoice

    async def test_duplicate_idempotency_key_violates_db_unique_constraint(self) -> None:
        """Regression, at the database layer: `ux_payments__idempotency_key` rejects a second
        `Payment` row with the same key even if the application-layer find-or-return check were
        somehow bypassed (e.g. a race between two concurrent requests neither of which has
        loaded the other's row yet)."""
        invoice = await self._seed_invoice()
        idempotency_key = f"dbtest-idem-{self.tag}"

        async with self._new_uow() as uow:
            first = Payment.initiate(
                id=PaymentId(self.id_generator.new_id()),
                organization_id=invoice.organization_id,
                invoice_id=invoice.id,
                provider="evcplus",
                msisdn_masked=None,
                amount=Money(15.00, "USD"),
                idempotency_key=idempotency_key,
                clock=self.clock,
            )
            uow.payments.add(first)
            uow.record_events(first.pull_domain_events())
            await uow.commit()
            self._created_payment_ids.append(str(first.id))

        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            async with self._new_uow() as uow:
                second = Payment.initiate(
                    id=PaymentId(self.id_generator.new_id()),
                    organization_id=invoice.organization_id,
                    invoice_id=invoice.id,
                    provider="evcplus",
                    msisdn_masked=None,
                    amount=Money(15.00, "USD"),
                    idempotency_key=idempotency_key,  # same key -> DB rejects
                    clock=self.clock,
                )
                uow.payments.add(second)
                uow.record_events(second.pull_domain_events())
                await uow.commit()
                self._created_payment_ids.append(str(second.id))

    async def test_duplicate_invoice_number_violates_db_unique_constraint(self) -> None:
        """Regression: `ux_invoices__number` (Database Design §8.3). `Invoice.issue()` always
        sets `number` to the invoice's own globally-unique id (`entities.py`'s own documented
        reasoning), so this can only be provoked by inserting a second row that reuses an
        already-issued invoice's `number` directly — proving the DB constraint actually exists
        and is wired, independent of the applicaton-layer numbering choice that happens to
        avoid ever colliding with it in practice."""
        first_invoice = await self._seed_invoice()

        async with self._new_uow() as uow:
            plan = Plan.create(
                id=PlanId(self.id_generator.new_id()),
                name=f"Plan {self.tag}-2",
                billing_scope=BillingScope.PARENT,
                price=Money(15.00, "USD"),
                billing_cycle=BillingCycle.MONTHLY,
                clock=self.clock,
            )
            uow.plans.add(plan)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
            self._created_plan_ids.append(str(plan.id))

            subscription = Subscription.open(
                id=SubscriptionId(self.id_generator.new_id()),
                organization_id=first_invoice.organization_id,
                subscriber_type=SubscriberType.PARENT,
                subscriber_id=SubscriberId(self.id_generator.new_id()),
                plan_id=plan.id,
                clock=self.clock,
            )
            uow.subscriptions.add(subscription)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
            self._created_subscription_ids.append(str(subscription.id))

        with self.assertRaises(sqlalchemy.exc.IntegrityError):
            async with self._new_uow() as uow:
                second_invoice = Invoice.issue(
                    id=InvoiceId(self.id_generator.new_id()),
                    organization_id=first_invoice.organization_id,
                    subscription_id=subscription.id,
                    amount=Money(15.00, "USD"),
                    period_start=date(2026, 8, 20),
                    period_end=date(2026, 9, 19),
                    due_at=None,
                    clock=self.clock,
                )
                second_invoice.number = str(first_invoice.id)  # force a collision
                uow.invoices.add(second_invoice)
                uow.record_events(second_invoice.pull_domain_events())
                await uow.commit()
                self._created_invoice_ids.append(str(second_invoice.id))


if __name__ == "__main__":
    unittest.main()
