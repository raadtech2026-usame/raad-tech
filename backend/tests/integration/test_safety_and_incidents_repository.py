"""Safety alerts and incidents against real PostgreSQL (ADR-0055, ADR-0056).

What only the database shows: the one-open-alert-per-bus-and-type partial index, CHAR padding
and tz handling on alert rows, `CHAR(26)[]` staff/student arrays, the timeline order, and tenant
scope on both.

**Requires a reachable PostgreSQL database** at `RAAD_DB__URL`, migrated to head.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import NotFoundError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.tracking.application.commands import RecordDeviceAlarmCommand
from raad.modules.tracking.application.ports import ActiveTripPort
from raad.modules.tracking.application.safety_services import SafetyAlertApplicationService
from raad.modules.tracking.infra.repositories import SqlAlchemyTrackingUnitOfWork
from raad.modules.transport_ops.application.incident_services import (
    IncidentApplicationService,
    RecordIncidentCommand,
)
from raad.modules.transport_ops.application.ports import VehicleDirectoryPort
from raad.modules.transport_ops.domain.entities import Student, TransportStaff
from raad.modules.transport_ops.domain.value_objects import OrganizationId, StudentId, TransportStaffId
from raad.modules.transport_ops.infra.repositories import SqlAlchemyTransportOpsUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


class _NoTrip(ActiveTripPort):
    async def active_trip_for_vehicle(self, vehicle_id):
        return None


class _Vehicles(VehicleDirectoryPort):
    def __init__(self, owners) -> None:
        self.owners = owners

    async def organization_of_vehicle(self, vehicle_id):
        return self.owners.get(vehicle_id)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class SafetyAndIncidentPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = build_engine(get_settings().db)
        self.session_factory = build_session_factory(self.engine)
        self.ids = UlidGenerator()
        self.clock = SystemClock()
        self.org = self.ids.new_id()
        self.other_org = self.ids.new_id()
        self.bus = self.ids.new_id()
        self.admin = Principal(user_id=self.ids.new_id(), role=Role.ORG_ADMIN, org_id=self.org)
        self.alerts = SafetyAlertApplicationService(
            clock=self.clock, id_generator=self.ids, active_trips=_NoTrip(), device_commands=None
        )
        self.incidents = IncidentApplicationService(
            clock=self.clock, id_generator=self.ids, vehicle_directory=_Vehicles({self.bus: self.org})
        )

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            for statement in (
                "DELETE FROM incident_notes WHERE organization_id = ANY(:orgs)",
                "DELETE FROM incidents WHERE organization_id = ANY(:orgs)",
                "DELETE FROM safety_alerts WHERE organization_id = ANY(:orgs)",
                "DELETE FROM transport_staff WHERE organization_id = ANY(:orgs)",
                "DELETE FROM students WHERE organization_id = ANY(:orgs)",
            ):
                await conn.execute(text(statement), {"orgs": [self.org, self.other_org]})
        await self.engine.dispose()

    def tracking_uow(self, *orgs):
        uow = SqlAlchemyTrackingUnitOfWork(self.session_factory, OutboxWriter(), AuditWriter())
        if orgs:
            uow.scope = TenantRegionScope(organization_ids=frozenset(orgs))
        return uow

    def ops_uow(self, *orgs):
        uow = SqlAlchemyTransportOpsUnitOfWork(self.session_factory, OutboxWriter(), AuditWriter())
        if orgs:
            uow.scope = TenantRegionScope(organization_ids=frozenset(orgs))
        return uow

    def alarm(self, alarm_type="sos"):
        now = datetime.now(timezone.utc)
        return RecordDeviceAlarmCommand(
            organization_id=self.org, vehicle_id=self.bus, device_id=None, terminal_id="00000000014482607571",
            alarm_type=alarm_type, event_time=now - timedelta(seconds=3), received_at=now, speed_kph=40.5,
        )

    async def test_alerts_repeat_into_one_row_and_the_index_backs_it(self) -> None:
        first = await self.alerts.record_device_alarm(self.alarm(), uow=self.tracking_uow())
        again = await self.alerts.record_device_alarm(self.alarm(), uow=self.tracking_uow())
        self.assertEqual((first.id, again.occurrences, again.vehicle_id), (again.id, 2, self.bus))
        self.assertFalse(again.is_late)
        with self.assertRaises(IntegrityError):
            async with self.engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO safety_alerts (id, created_at, updated_at, row_version, organization_id, vehicle_id, "
                        "terminal_id, alarm_type, status, raised_at, last_raised_at, received_at, occurrences) VALUES "
                        "(:id, now(), now(), 1, :org, :bus, 'T', 'sos', 'acknowledged', now(), now(), now(), 1)"
                    ),
                    {"id": self.ids.new_id(), "org": self.org, "bus": self.bus},
                )
        await self.alerts.mark_false_alarm(first.id, actor=self.admin, uow=self.tracking_uow())
        fresh = await self.alerts.record_device_alarm(self.alarm(), uow=self.tracking_uow())
        self.assertNotEqual(fresh.id, first.id)

    async def test_alerts_are_tenant_scoped(self) -> None:
        alert = await self.alerts.record_device_alarm(self.alarm("collision"), uow=self.tracking_uow())
        with self.assertRaises(NotFoundError):
            await self.alerts.get_alert(alert.id, uow=self.tracking_uow(self.other_org))
        from raad.modules.tracking.application.queries import ListSafetyAlertsQuery

        mine = await self.alerts.list_alerts(ListSafetyAlertsQuery(statuses=["open"]), uow=self.tracking_uow(self.org))
        self.assertEqual([a.id for a in mine], [alert.id])

    async def test_incident_arrays_timeline_and_scope(self) -> None:
        org = OrganizationId(self.org)
        async with self.ops_uow() as uow:
            student = Student.enroll(id=StudentId(self.ids.new_id()), organization_id=org, full_name="Child", clock=self.clock)
            staff = TransportStaff.register(id=TransportStaffId(self.ids.new_id()), organization_id=org, full_name="Amina", clock=self.clock)
            uow.students.add(student)
            uow.staff.add(staff)
            uow.record_events(student.pull_domain_events() + staff.pull_domain_events())
            await uow.commit()
        incident = await self.incidents.record(
            RecordIncidentCommand(
                organization_id=self.org, category="medical", severity="high", occurred_at=datetime.now(timezone.utc),
                title="Child unwell", vehicle_id=self.bus, staff_ids=(str(staff.id),), student_ids=(str(student.id),),
                actor=self.admin,
            ),
            uow=self.ops_uow(),
        )
        await self.incidents.add_note(incident.id, "Called the parents.", actor=self.admin, uow=self.ops_uow())
        await self.incidents.change_status(
            incident.id, "closed", resolution="Collected by parents", recorded_in_error=False, actor=self.admin, uow=self.ops_uow()
        )
        fetched = await self.incidents.get(incident.id, uow=self.ops_uow(self.org))
        self.assertEqual((fetched.staff_ids, fetched.student_ids), ([str(staff.id)], [str(student.id)]))
        self.assertEqual((fetched.staff_names, fetched.student_names), (["Amina"], ["Child"]))
        self.assertEqual([n.kind for n in fetched.notes], ["note", "status_change"])
        self.assertEqual(fetched.status, "closed")
        with self.assertRaises(NotFoundError):
            await self.incidents.get(incident.id, uow=self.ops_uow(self.other_org))


if __name__ == "__main__":
    unittest.main()
