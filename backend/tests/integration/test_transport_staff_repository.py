"""Transport staff, crew assignments and documents against real PostgreSQL (ADR-0049..0051).

What only a real database can show: the partial unique indexes, the `drivers.staff_id` foreign
key and its flush order, the self-referencing renewal link, `CHAR(26)` padding on the new id
columns, the `SMALLINT[]` lead days, and tenant scope applied by the repositories.

**Requires a reachable PostgreSQL database** at `RAAD_DB__URL`, migrated to head.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import OffsetPageRequest
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.application.commands import (
    AddDefaultStaffSetupCommand,
    AssignStaffToVehicleCommand,
    ChangeTransportStaffStatusCommand,
    GrantDriverAccessCommand,
    RecordStaffDocumentCommand,
    RegisterTransportStaffCommand,
    SaveStaffDocumentTypeCommand,
)
from raad.modules.transport_ops.application.ports import (
    UserProvisioningPort,
    VehicleDirectoryPort,
)
from raad.modules.transport_ops.application.queries import ListTransportStaffQuery
from raad.modules.transport_ops.application.staff_services import (
    TransportStaffApplicationService,
)
from raad.modules.transport_ops.infra.repositories import SqlAlchemyTransportOpsUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."

_CLEANUP = (
    "DELETE FROM staff_documents WHERE organization_id = ANY(:orgs)",
    "DELETE FROM vehicle_staff_assignments WHERE organization_id = ANY(:orgs)",
    "DELETE FROM drivers WHERE organization_id = ANY(:orgs)",
    "DELETE FROM transport_staff WHERE organization_id = ANY(:orgs)",
    "DELETE FROM staff_document_types WHERE organization_id = ANY(:orgs)",
    "DELETE FROM transport_staff_roles WHERE organization_id = ANY(:orgs)",
)


class _Vehicles(VehicleDirectoryPort):
    def __init__(self) -> None:
        self.owners: dict[str, str] = {}

    async def organization_of_vehicle(self, vehicle_id: str) -> str | None:
        return self.owners.get(vehicle_id)


class _Provisioning(UserProvisioningPort):
    def __init__(self, ids: UlidGenerator) -> None:
        self._ids = ids

    async def create_user_with_temporary_password(self, **kwargs) -> tuple[str, str]:
        return self._ids.new_id(), "temp-pass"


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class TransportStaffPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = build_engine(get_settings().db)
        self.session_factory = build_session_factory(self.engine)
        self.ids = UlidGenerator()
        self.org = self.ids.new_id()
        self.other_org = self.ids.new_id()
        self.bus = self.ids.new_id()
        self.vehicles = _Vehicles()
        self.vehicles.owners[self.bus] = self.org
        self.service = TransportStaffApplicationService(
            clock=SystemClock(),
            id_generator=self.ids,
            user_provisioning=_Provisioning(self.ids),
            vehicle_directory=self.vehicles,
        )
        self.admin = Principal(user_id=self.ids.new_id(), role=Role.ORG_ADMIN, org_id=self.org)

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            for statement in _CLEANUP:
                await conn.execute(text(statement), {"orgs": [self.org, self.other_org]})
        await self.engine.dispose()

    def uow(self, *orgs: str) -> SqlAlchemyTransportOpsUnitOfWork:
        uow = SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, OutboxWriter(), AuditWriter()
        )
        if orgs:
            uow.scope = TenantRegionScope(organization_ids=frozenset(orgs))
        return uow

    async def register(self, **overrides):
        values = dict(organization_id=self.org, full_name="Amina Warsame", actor=self.admin)
        values.update(overrides)
        return await self.service.register_staff(
            RegisterTransportStaffCommand(**values), uow=self.uow()
        )

    async def test_defaults_and_staff_round_trip_without_char_padding(self) -> None:
        setup = AddDefaultStaffSetupCommand(organization_id=self.org, actor=self.admin)
        roles = await self.service.add_default_roles(setup, uow=self.uow())
        types = await self.service.add_default_document_types(setup, uow=self.uow())
        again = await self.service.add_default_roles(setup, uow=self.uow())
        self.assertEqual(len(again), len(roles))
        self.assertEqual(types[0].alert_lead_days, [30, 7])

        driver_title = next(r for r in roles if r.name == "Driver")
        staff = await self.register(role_id=driver_title.id, phone="+252611234567")
        fetched = await self.service.get_staff(staff.id, uow=self.uow())
        self.assertEqual(fetched.role_id, driver_title.id)  # no CHAR(26) padding
        self.assertEqual(fetched.role_name, "Driver")
        self.assertEqual(fetched.phone, "+252611234567")

    async def test_employee_ref_unique_only_when_set(self) -> None:
        await self.register(full_name="A")
        await self.register(full_name="B")  # two NULL references are fine
        await self.register(full_name="C", employee_ref="E-1")
        with self.assertRaises(ConflictError):
            await self.register(full_name="D", employee_ref="E-1")
        # The database refuses it too, for a writer that skips the service check.
        with self.assertRaises(IntegrityError):
            async with self.engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO transport_staff (id, created_at, updated_at, row_version, "
                        "organization_id, full_name, employee_ref, status) VALUES "
                        "(:id, now(), now(), 1, :org, 'E', 'E-1', 'active')"
                    ),
                    {"id": self.ids.new_id(), "org": self.org},
                )

    async def test_tenant_scope_hides_another_organizations_staff(self) -> None:
        staff = await self.register()
        with self.assertRaises(NotFoundError):
            await self.service.get_staff(staff.id, uow=self.uow(self.other_org))
        page = await self.service.list_staff(
            ListTransportStaffQuery(page_request=OffsetPageRequest(page=1, page_size=100)),
            uow=self.uow(self.other_org),
        )
        self.assertNotIn(staff.id, [s.id for s in page.data])
        crew = await self.service.list_assignments(uow=self.uow(self.other_org), vehicle_id=self.bus)
        self.assertEqual(crew, [])

    async def test_one_open_assignment_per_person_per_bus_is_enforced_by_the_database(
        self,
    ) -> None:
        staff = await self.register()
        first = await self.service.assign_to_vehicle(
            AssignStaffToVehicleCommand(
                staff_id=staff.id, vehicle_id=self.bus, kind="permanent", actor=self.admin
            ),
            uow=self.uow(),
        )
        self.assertEqual(first.vehicle_id, self.bus)
        with self.assertRaises(IntegrityError):
            async with self.engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO vehicle_staff_assignments (id, created_at, updated_at, "
                        "row_version, organization_id, staff_id, vehicle_id, starts_on, kind) "
                        "VALUES (:id, now(), now(), 1, :org, :staff, :bus, :d, 'permanent')"
                    ),
                    {
                        "id": self.ids.new_id(),
                        "org": self.org,
                        "staff": staff.id,
                        "bus": self.bus,
                        "d": date.today() + timedelta(days=30),
                    },
                )

    async def test_leaving_persists_ended_crew_and_disabled_driver(self) -> None:
        staff = await self.register(phone="+252611234567")
        driver, _ = await self.service.grant_driver_access(
            GrantDriverAccessCommand(
                staff_id=staff.id, license_no="DL-1", email=None, phone=None, actor=self.admin
            ),
            uow=self.uow(),
        )
        self.assertEqual(driver.staff_id, staff.id)
        await self.service.assign_to_vehicle(
            AssignStaffToVehicleCommand(
                staff_id=staff.id, vehicle_id=self.bus, kind="permanent", actor=self.admin
            ),
            uow=self.uow(),
        )
        with self.assertRaises(ConflictError):
            await self.service.grant_driver_access(
                GrantDriverAccessCommand(
                    staff_id=staff.id, license_no="DL-2", email=None, phone=None, actor=self.admin
                ),
                uow=self.uow(),
            )

        left = await self.service.change_status(
            ChangeTransportStaffStatusCommand(staff_id=staff.id, status="left", actor=self.admin),
            uow=self.uow(),
        )

        self.assertEqual(left.driver.status, "inactive")
        crew = await self.service.list_assignments(uow=self.uow(), vehicle_id=self.bus)
        self.assertEqual(crew[0].ends_on, date.today())
        current = await self.service.list_assignments(
            uow=self.uow(), vehicle_id=self.bus, current_only=True
        )
        # `ends_on` is inclusive and `left_on` is their last day: still on today's crew.
        self.assertEqual([c.staff_id for c in current], [staff.id])

    async def test_renewal_links_documents_and_alerts_persist(self) -> None:
        staff = await self.register()
        licence = await self.service.save_document_type(
            SaveStaffDocumentTypeCommand(
                organization_id=self.org,
                name="Driving licence",
                alert_lead_days=(30, 7),
                actor=self.admin,
            ),
            uow=self.uow(),
        )
        old = await self.service.record_document(
            RecordStaffDocumentCommand(
                staff_id=staff.id,
                type_id=licence.id,
                number="DL-OLD",
                expires_on=date.today() + timedelta(days=5),
                actor=self.admin,
            ),
            uow=self.uow(),
        )
        alerts = await self.service.collect_due_expiry_alerts(uow=self.uow(self.org))
        self.assertEqual([(a.document_id, a.threshold_days) for a in alerts], [(old.id, 7)])
        await self.service.mark_expiry_alerted(old.id, 7, uow=self.uow())
        self.assertEqual(await self.service.collect_due_expiry_alerts(uow=self.uow(self.org)), [])

        new = await self.service.record_document(
            RecordStaffDocumentCommand(
                staff_id=staff.id,
                type_id=licence.id,
                number="DL-NEW",
                expires_on=date.today() + timedelta(days=5 * 365),
                replaces_id=old.id,
                actor=self.admin,
            ),
            uow=self.uow(),
        )
        documents = {
            d.id: d for d in await self.service.list_documents_for_staff(staff.id, uow=self.uow())
        }
        self.assertEqual(documents[old.id].replaced_by_id, new.id)
        self.assertEqual(documents[old.id].status, "superseded")
        self.assertEqual(documents[new.id].status, "valid")
        self.assertEqual(
            await self.service.list_expiring_documents(uow=self.uow(), organization_id=self.org),
            [],
        )


if __name__ == "__main__":
    unittest.main()
