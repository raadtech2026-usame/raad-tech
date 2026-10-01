"""Document requirements and compliance against real PostgreSQL (ADR-0058, ADR-0059).

What only the database shows: the two enum columns and their defaults, `CHAR(26)` ids compared
across three tables without padding, the scoped "required types" and "current documents"
queries, and the planning check reading before the first INSERT.

**Requires a reachable PostgreSQL database** at `RAAD_DB__URL`, migrated to head.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import NotFoundError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.application.commands import (
    AssignStaffToVehicleCommand,
    ChangeTransportStaffStatusCommand,
    GrantDriverAccessCommand,
    RecordStaffDocumentCommand,
    RegisterTransportStaffCommand,
    SaveStaffDocumentTypeCommand,
)
from raad.modules.transport_ops.application.ports import UserProvisioningPort, VehicleDirectoryPort
from raad.modules.transport_ops.application.staff_services import TransportStaffApplicationService
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
)


class _Vehicles(VehicleDirectoryPort):
    def __init__(self, owners) -> None:
        self.owners = owners

    async def organization_of_vehicle(self, vehicle_id: str) -> str | None:
        return self.owners.get(vehicle_id)


class _Provisioning(UserProvisioningPort):
    def __init__(self, ids: UlidGenerator) -> None:
        self._ids = ids

    async def create_user_with_temporary_password(self, **kwargs) -> tuple[str, str]:
        return self._ids.new_id(), "temp-pass"


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class DocumentCompliancePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = build_engine(get_settings().db)
        self.session_factory = build_session_factory(self.engine)
        self.ids = UlidGenerator()
        self.org = self.ids.new_id()
        self.other_org = self.ids.new_id()
        self.bus = self.ids.new_id()
        self.service = TransportStaffApplicationService(
            clock=SystemClock(),
            id_generator=self.ids,
            user_provisioning=_Provisioning(self.ids),
            vehicle_directory=_Vehicles({self.bus: self.org}),
        )
        self.admin = Principal(user_id=self.ids.new_id(), role=Role.ORG_ADMIN, org_id=self.org)
        self.other_admin = Principal(user_id=self.ids.new_id(), role=Role.ORG_ADMIN, org_id=self.other_org)
        # The service's own "today" (UTC), not the machine's local date.
        self.today = datetime.now(timezone.utc).date()

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            for statement in _CLEANUP:
                await conn.execute(text(statement), {"orgs": [self.org, self.other_org]})
        await self.engine.dispose()

    def uow(self, *orgs: str) -> SqlAlchemyTransportOpsUnitOfWork:
        uow = SqlAlchemyTransportOpsUnitOfWork(self.session_factory, OutboxWriter(), AuditWriter())
        if orgs:
            uow.scope = TenantRegionScope(organization_ids=frozenset(orgs))
        return uow

    async def person(self, name, *, driver=False, admin=None, org=None):
        admin = admin or self.admin
        staff = await self.service.register_staff(
            RegisterTransportStaffCommand(organization_id=org or self.org, full_name=name, actor=admin),
            uow=self.uow(),
        )
        if driver:
            await self.service.grant_driver_access(
                GrantDriverAccessCommand(
                    staff_id=staff.id, license_no=f"DL-{self.ids.new_id()[-6:]}", email=None, phone=None, actor=admin
                ),
                uow=self.uow(),
            )
        return staff

    async def a_type(self, name, *, admin=None, org=None, **settings):
        admin = admin or self.admin
        return await self.service.save_document_type(
            SaveStaffDocumentTypeCommand(
                organization_id=org or self.org, name=name, alert_lead_days=(30, 7), actor=admin, **settings
            ),
            uow=self.uow(),
        )

    async def hold(self, staff, doc_type, expires_on, **extra):
        return await self.service.record_document(
            RecordStaffDocumentCommand(
                staff_id=staff.id, type_id=doc_type.id, number="NUM-SECRET", expires_on=expires_on,
                actor=self.admin, **extra,
            ),
            uow=self.uow(),
        )

    async def test_requirement_columns_round_trip_and_default_to_no_change(self) -> None:
        plain = await self.a_type("Other")
        self.assertEqual((plain.required_for, plain.enforcement), ("none", "warn"))
        licence = await self.a_type("Driving licence", required_for="drivers", enforcement="block")
        listed = {t.name: t for t in await self.service.list_document_types(self.org, uow=self.uow(self.org))}
        self.assertEqual(
            (listed["Driving licence"].required_for, listed["Driving licence"].enforcement), ("drivers", "block")
        )
        # A row written without the new columns (as every pre-Phase-4 row was) is `none`/`warn`.
        legacy = self.ids.new_id()
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO staff_document_types (id, created_at, updated_at, row_version, organization_id, "
                    "name, alert_lead_days, is_archived) VALUES (:id, now(), now(), 1, :org, 'Legacy', '{30}', false)"
                ),
                {"id": legacy, "org": self.org},
            )
        listed = {t.name: t for t in await self.service.list_document_types(self.org, uow=self.uow(self.org))}
        self.assertEqual((listed["Legacy"].required_for, listed["Legacy"].enforcement), ("none", "warn"))
        self.assertEqual(licence.id, listed["Driving licence"].id)  # no CHAR(26) padding

    async def test_compliance_through_real_joins_and_renewal(self) -> None:
        licence = await self.a_type("Driving licence", required_for="drivers")
        medical = await self.a_type("Medical certificate", required_for="all_staff", enforcement="block")
        amina = await self.person("Amina", driver=True)
        fatima = await self.person("Fatima")

        record = await self.service.get_staff(amina.id, uow=self.uow(self.org))
        self.assertEqual(
            sorted((g.type_name, g.reason, g.blocks) for g in record.compliance.gaps),
            [("Driving licence", "missing", False), ("Medical certificate", "missing", True)],
        )
        attendant = await self.service.get_staff(fatima.id, uow=self.uow(self.org))
        self.assertEqual([g.type_name for g in attendant.compliance.gaps], ["Medical certificate"])

        old = await self.hold(amina, licence, self.today - timedelta(days=1))
        await self.hold(amina, medical, None)
        record = await self.service.get_staff(amina.id, uow=self.uow(self.org))
        self.assertEqual(
            [(g.type_name, g.reason, g.expired_on) for g in record.compliance.gaps],
            [("Driving licence", "expired", self.today - timedelta(days=1))],
        )
        await self.hold(amina, licence, self.today + timedelta(days=400), replaces_id=old.id)
        record = await self.service.get_staff(amina.id, uow=self.uow(self.org))
        self.assertEqual((record.compliance.status, record.compliance.gaps), ("compliant", []))

        page_rows = await self.service.list_staff_compliance(uow=self.uow(self.org))
        self.assertEqual([(r.staff_name, r.compliance.status) for r in page_rows], [("Fatima", "not_compliant")])
        self.assertNotIn("NUM-SECRET", repr(page_rows) + repr(record.compliance))

    async def test_compliance_and_impact_are_tenant_scoped(self) -> None:
        licence = await self.a_type("Driving licence", required_for="drivers")
        await self.person("Amina", driver=True)
        await self.a_type("Driving licence", admin=self.other_admin, org=self.other_org, required_for="all_staff")
        await self.person("Elsewhere", admin=self.other_admin, org=self.other_org)

        mine = await self.service.list_staff_compliance(uow=self.uow(self.org))
        theirs = await self.service.list_staff_compliance(uow=self.uow(self.other_org))
        self.assertEqual(([r.staff_name for r in mine], [r.staff_name for r in theirs]), (["Amina"], ["Elsewhere"]))

        impact = await self.service.document_type_impact(licence.id, "all_staff", uow=self.uow(self.org))
        self.assertEqual((impact.applies_to, impact.not_compliant), (1, 1))
        with self.assertRaises(NotFoundError):
            await self.service.document_type_impact(licence.id, "drivers", uow=self.uow(self.other_org))

    async def test_someone_who_left_has_no_compliance_and_crew_assignment_only_warns(self) -> None:
        await self.a_type("Medical certificate", required_for="all_staff", enforcement="block")
        fatima = await self.person("Fatima")
        assignment = await self.service.assign_to_vehicle(
            AssignStaffToVehicleCommand(staff_id=fatima.id, vehicle_id=self.bus, kind="permanent", actor=self.admin),
            uow=self.uow(),
        )
        self.assertEqual(len(assignment.warnings), 1)
        left = await self.service.change_status(
            ChangeTransportStaffStatusCommand(staff_id=fatima.id, status="left", actor=self.admin), uow=self.uow()
        )
        self.assertIsNone(left.compliance)
        self.assertEqual(await self.service.list_staff_compliance(uow=self.uow(self.org)), [])


if __name__ == "__main__":
    unittest.main()
