"""`TransportStaffApplicationService` against in-memory fakes (ADR-0049, ADR-0050, ADR-0051)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from raad.core.errors.exceptions import (
    AuthorizationError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import FilterCondition, OffsetPageRequest
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from _transport_staff_fakes import attach_staff_repositories
from raad.modules.transport_ops.application.commands import (
    AddDefaultStaffSetupCommand,
    AssignStaffToVehicleCommand,
    ChangeTransportStaffStatusCommand,
    EndStaffAssignmentCommand,
    GrantDriverAccessCommand,
    RecordStaffDocumentCommand,
    RegisterTransportStaffCommand,
    SaveStaffDocumentTypeCommand,
    SaveStaffRoleCommand,
    UpdateStaffDocumentCommand,
    UpdateTransportStaffCommand,
)
from raad.modules.transport_ops.application.ports import (
    TransportOpsUnitOfWork,
    UserProvisioningPort,
    VehicleDirectoryPort,
)
from raad.modules.transport_ops.application.queries import ListTransportStaffQuery
from raad.modules.transport_ops.application.staff_services import (
    DEFAULT_STAFF_DOCUMENT_TYPES,
    DEFAULT_STAFF_ROLES,
    TransportStaffApplicationService,
)
from raad.modules.transport_ops.domain.entities import Driver, Route
from raad.modules.transport_ops.domain.repositories import DriverRepository, RouteRepository
from raad.modules.transport_ops.domain.value_objects import (
    DriverStatus,
    OrganizationId,
    RouteId,
    RouteStatus,
)

ORG = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
BUS = "01J8Z3K9G6X8YV5T4N2R7QW3VA"
OTHER_BUS = "01J8Z3K9G6X8YV5T4N2R7QW3VB"
NOW = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
TODAY = NOW.date()


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class SequentialIds(IdGenerator):
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"01J8Z3K9G6X8YV5T4N2R7Q{self._n:04d}"


class _Drivers(DriverRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Driver] = {}

    async def get(self, driver_id):
        return self.by_id.get(str(driver_id))

    async def get_by_user_id(self, user_id):
        return None

    async def get_by_staff_id(self, staff_id):
        return next((d for d in self.by_id.values() if d.staff_id == staff_id), None)

    async def list_by_staff_ids(self, staff_ids):
        return [d for d in self.by_id.values() if str(d.staff_id) in set(staff_ids)]

    def add(self, driver: Driver) -> None:
        self.by_id[str(driver.id)] = driver

    async def list_all(self):
        return list(self.by_id.values())

    async def list_page(self, page_request, *, sort, filters, search):
        raise NotImplementedError


class _Routes(RouteRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Route] = {}

    async def get(self, route_id):
        return self.by_id.get(str(route_id))

    async def get_by_name(self, name):
        return None

    def add(self, route):
        self.by_id[str(route.id)] = route

    async def list_all(self):
        return list(self.by_id.values())

    async def list_page(self, page_request, *, sort, filters, search):
        raise NotImplementedError


class FakeUow(TransportOpsUnitOfWork):
    def __init__(self) -> None:
        self.drivers = _Drivers()
        self.routes = _Routes()
        attach_staff_repositories(self)
        self.recorded_events: list = []
        self.commit_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        pass


class FakeProvisioning(UserProvisioningPort):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_user_with_temporary_password(self, **kwargs) -> tuple[str, str]:
        self.calls.append(kwargs)
        return "01J8Z3K9G6X8YV5T4N2R7QW3US", "temp-pass"


class FakeVehicles(VehicleDirectoryPort):
    def __init__(self) -> None:
        self.owners = {BUS: ORG, OTHER_BUS: OTHER_ORG}

    async def organization_of_vehicle(self, vehicle_id: str) -> str | None:
        return self.owners.get(vehicle_id)


def admin(org: str = ORG) -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=org)


class StaffServiceTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.provisioning = FakeProvisioning()
        self.vehicles = FakeVehicles()
        self.service = TransportStaffApplicationService(
            clock=FixedClock(),
            id_generator=SequentialIds(),
            user_provisioning=self.provisioning,
            vehicle_directory=self.vehicles,
        )
        self.uow = FakeUow()

    async def register(self, **overrides):
        values = dict(organization_id=ORG, full_name="Amina Warsame", actor=admin())
        values.update(overrides)
        return await self.service.register_staff(
            RegisterTransportStaffCommand(**values), uow=self.uow
        )

    async def assign(self, staff_id: str, **overrides):
        values = dict(staff_id=staff_id, vehicle_id=BUS, kind="permanent", actor=admin())
        values.update(overrides)
        return await self.service.assign_to_vehicle(
            AssignStaffToVehicleCommand(**values), uow=self.uow
        )


class SetupTests(StaffServiceTestCase):
    async def test_default_titles_and_types_are_added_once(self) -> None:
        command = AddDefaultStaffSetupCommand(organization_id=ORG, actor=admin())
        await self.service.add_default_roles(command, uow=self.uow)
        roles = await self.service.add_default_roles(command, uow=self.uow)
        self.assertEqual([r.name for r in roles], list(DEFAULT_STAFF_ROLES))
        await self.service.add_default_document_types(command, uow=self.uow)
        types = await self.service.add_default_document_types(command, uow=self.uow)
        self.assertEqual(len(types), len(DEFAULT_STAFF_DOCUMENT_TYPES))
        self.assertTrue(all(t.alert_lead_days == [30, 7] for t in types))

    async def test_duplicate_title_names_are_refused_ignoring_case(self) -> None:
        await self.service.save_role(
            SaveStaffRoleCommand(organization_id=ORG, name="Attendant", sort_order=1, actor=admin()),
            uow=self.uow,
        )
        with self.assertRaises(ConflictError):
            await self.service.save_role(
                SaveStaffRoleCommand(
                    organization_id=ORG, name=" attendant ", sort_order=2, actor=admin()
                ),
                uow=self.uow,
            )

    async def test_org_admin_cannot_set_up_another_organization(self) -> None:
        with self.assertRaises(AuthorizationError):
            await self.service.add_default_roles(
                AddDefaultStaffSetupCommand(organization_id=OTHER_ORG, actor=admin()),
                uow=self.uow,
            )

    async def test_another_organizations_title_is_not_found(self) -> None:
        other = await self.service.save_role(
            SaveStaffRoleCommand(
                organization_id=OTHER_ORG,
                name="Attendant",
                sort_order=1,
                actor=Principal(user_id="f", role=Role.FOUNDER, org_id=None),
            ),
            uow=self.uow,
        )
        with self.assertRaises(NotFoundError):
            await self.register(role_id=other.id)

    async def test_archived_title_cannot_be_newly_chosen(self) -> None:
        role = await self.service.save_role(
            SaveStaffRoleCommand(organization_id=ORG, name="Conductor", sort_order=1, actor=admin()),
            uow=self.uow,
        )
        await self.service.save_role(
            SaveStaffRoleCommand(
                organization_id=ORG,
                name="Conductor",
                sort_order=1,
                actor=admin(),
                role_id=role.id,
                is_archived=True,
            ),
            uow=self.uow,
        )
        with self.assertRaises(DomainError):
            await self.register(role_id=role.id)


class StaffRecordTests(StaffServiceTestCase):
    async def test_register_and_read_back(self) -> None:
        dto = await self.register(
            phone=" +252611234567 ", employee_ref="E-1", emergency_contact_name=""
        )
        self.assertEqual(dto.status, "active")
        self.assertEqual(dto.phone, "+252611234567")
        self.assertIsNone(dto.emergency_contact_name)  # blank means "not set"
        self.assertIsNone(dto.driver)
        page = await self.service.list_staff(
            ListTransportStaffQuery(page_request=OffsetPageRequest(page=1, page_size=20)),
            uow=self.uow,
        )
        self.assertEqual(page.total, 1)
        self.assertFalse(page.data[0].is_driver)

    async def test_employee_ref_is_unique_within_the_organization(self) -> None:
        await self.register(employee_ref="E-1")
        with self.assertRaises(ConflictError):
            await self.register(full_name="Someone Else", employee_ref="E-1")
        other = await self.register(full_name="Second")
        with self.assertRaises(ConflictError):
            await self.service.update_staff(
                UpdateTransportStaffCommand(
                    staff_id=other.id, changes={"employee_ref": "E-1"}, actor=admin()
                ),
                uow=self.uow,
            )

    async def test_update_changes_only_given_fields(self) -> None:
        dto = await self.register(phone="+252611234567")
        updated = await self.service.update_staff(
            UpdateTransportStaffCommand(
                staff_id=dto.id, changes={"alternate_phone": "+252617654321"}, actor=admin()
            ),
            uow=self.uow,
        )
        self.assertEqual(updated.phone, "+252611234567")
        self.assertEqual(updated.alternate_phone, "+252617654321")

    async def test_leaving_ends_crew_assignments_and_disables_the_driver_in_one_commit(
        self,
    ) -> None:
        dto = await self.register(phone="+252611234567")
        await self.service.grant_driver_access(
            GrantDriverAccessCommand(
                staff_id=dto.id, license_no="DL-1", email=None, phone=None, actor=admin()
            ),
            uow=self.uow,
        )
        current = await self.assign(dto.id)
        commits_before = self.uow.commit_count
        left = await self.service.change_status(
            ChangeTransportStaffStatusCommand(staff_id=dto.id, status="left", actor=admin()),
            uow=self.uow,
        )
        self.assertEqual(self.uow.commit_count, commits_before + 1)
        self.assertEqual(left.left_on, TODAY)
        self.assertEqual(self.uow.staff_assignments.by_id[current.id].ends_on, TODAY)
        self.assertEqual(left.driver.status, DriverStatus.INACTIVE.value)


class DriverAccessTests(StaffServiceTestCase):
    async def test_grant_uses_the_staff_name_and_phone(self) -> None:
        dto = await self.register(phone="+252611234567")
        driver, password = await self.service.grant_driver_access(
            GrantDriverAccessCommand(
                staff_id=dto.id, license_no="DL-1", email=None, phone=None, actor=admin()
            ),
            uow=self.uow,
        )
        self.assertEqual(password, "temp-pass")
        self.assertEqual(driver.staff_id, dto.id)
        call = self.provisioning.calls[0]
        self.assertEqual((call["full_name"], call["phone"]), ("Amina Warsame", "+252611234567"))
        self.assertIs(call["role"], Role.DRIVER)

    async def test_grant_twice_is_a_conflict(self) -> None:
        dto = await self.register()
        command = GrantDriverAccessCommand(
            staff_id=dto.id, license_no="DL-1", email="a@example.com", phone=None, actor=admin()
        )
        await self.service.grant_driver_access(command, uow=self.uow)
        with self.assertRaises(ConflictError):
            await self.service.grant_driver_access(command, uow=self.uow)
        self.assertEqual(len(self.provisioning.calls), 1)

    async def test_inactive_staff_cannot_be_given_access(self) -> None:
        dto = await self.register()
        await self.service.change_status(
            ChangeTransportStaffStatusCommand(staff_id=dto.id, status="inactive", actor=admin()),
            uow=self.uow,
        )
        with self.assertRaises(DomainError):
            await self.service.grant_driver_access(
                GrantDriverAccessCommand(
                    staff_id=dto.id, license_no="DL-1", email=None, phone=None, actor=admin()
                ),
                uow=self.uow,
            )
        self.assertEqual(self.provisioning.calls, [])


class CrewAssignmentTests(StaffServiceTestCase):
    async def test_assignment_snapshots_the_current_title(self) -> None:
        role = await self.service.save_role(
            SaveStaffRoleCommand(organization_id=ORG, name="Attendant", sort_order=1, actor=admin()),
            uow=self.uow,
        )
        dto = await self.register(role_id=role.id)
        assignment = await self.assign(dto.id)
        self.assertEqual((assignment.role_id, assignment.role_name), (role.id, "Attendant"))
        self.assertEqual(assignment.starts_on, TODAY)
        self.assertTrue(assignment.is_current)

    async def test_a_bus_in_another_organization_is_not_found(self) -> None:
        dto = await self.register()
        for vehicle in (OTHER_BUS, "01J8Z3K9G6X8YV5T4N2R7QW3VZ"):
            with self.subTest(vehicle=vehicle), self.assertRaises(NotFoundError):
                await self.assign(dto.id, vehicle_id=vehicle)

    async def test_a_route_in_another_organization_is_not_found(self) -> None:
        route = Route(
            id=RouteId("01J8Z3K9G6X8YV5T4N2R7QW3RR"),
            organization_id=OrganizationId(OTHER_ORG),
            name="Other",
            status=RouteStatus.ACTIVE,
            stops=[],
            created_at=NOW,
            updated_at=NOW,
        )
        self.uow.routes.add(route)
        dto = await self.register()
        with self.assertRaises(NotFoundError):
            await self.assign(dto.id, route_id=str(route.id))

    async def test_overlapping_assignment_to_the_same_bus_is_a_conflict(self) -> None:
        dto = await self.register()
        await self.assign(dto.id)
        with self.assertRaises(ConflictError):
            await self.assign(
                dto.id, kind="temporary", starts_on=date(2026, 10, 5), ends_on=date(2026, 10, 9)
            )

    async def test_one_person_may_be_on_several_buses(self) -> None:
        self.vehicles.owners["01J8Z3K9G6X8YV5T4N2R7QW3VC"] = ORG
        dto = await self.register()
        await self.assign(dto.id)
        await self.assign(dto.id, vehicle_id="01J8Z3K9G6X8YV5T4N2R7QW3VC")
        rows = await self.service.list_assignments(uow=self.uow, staff_id=dto.id)
        self.assertEqual(len(rows), 2)

    async def test_ending_keeps_history_and_frees_the_bus_for_a_new_row(self) -> None:
        dto = await self.register()
        first = await self.assign(dto.id, starts_on=date(2026, 9, 1))
        await self.service.end_assignment(
            EndStaffAssignmentCommand(assignment_id=first.id, actor=admin(), ends_on=TODAY),
            uow=self.uow,
        )
        await self.assign(dto.id, starts_on=date(2026, 10, 1))
        all_rows = await self.service.list_assignments(uow=self.uow, vehicle_id=BUS)
        current = await self.service.list_assignments(
            uow=self.uow, vehicle_id=BUS, current_only=True
        )
        self.assertEqual(len(all_rows), 2)
        self.assertEqual(len(current), 1)  # the first ends today; the second starts tomorrow

    async def test_inactive_staff_cannot_be_assigned(self) -> None:
        dto = await self.register()
        await self.service.change_status(
            ChangeTransportStaffStatusCommand(staff_id=dto.id, status="inactive", actor=admin()),
            uow=self.uow,
        )
        with self.assertRaises(DomainError):
            await self.assign(dto.id)


class DocumentTests(StaffServiceTestCase):
    async def asyncSetUp(self) -> None:
        self.staff = await self.register()
        self.licence = await self.service.save_document_type(
            SaveStaffDocumentTypeCommand(
                organization_id=ORG, name="Driving licence", alert_lead_days=(30, 7), actor=admin()
            ),
            uow=self.uow,
        )

    async def record(self, **overrides):
        values = dict(staff_id=self.staff.id, type_id=self.licence.id, actor=admin())
        values.update(overrides)
        return await self.service.record_document(
            RecordStaffDocumentCommand(**values), uow=self.uow
        )

    async def test_status_and_days_left_are_computed(self) -> None:
        doc = await self.record(number="DL-1", expires_on=date(2026, 10, 10))
        self.assertEqual((doc.status, doc.days_left), ("expiring", 10))
        expiring = await self.service.list_expiring_documents(uow=self.uow)
        self.assertEqual([d.id for d in expiring], [doc.id])

    async def test_renewal_supersedes_the_old_document(self) -> None:
        old = await self.record(expires_on=date(2026, 10, 10))
        new = await self.record(expires_on=date(2031, 10, 10), replaces_id=old.id)
        docs = {d.id: d for d in await self.service.list_documents_for_staff(
            self.staff.id, uow=self.uow
        )}
        self.assertEqual(docs[old.id].status, "superseded")
        self.assertEqual(docs[old.id].replaced_by_id, new.id)
        self.assertEqual(await self.service.list_expiring_documents(uow=self.uow), [])
        with self.assertRaises(ConflictError):
            await self.record(expires_on=date(2032, 1, 1), replaces_id=old.id)

    async def test_renewal_must_be_the_same_type(self) -> None:
        medical = await self.service.save_document_type(
            SaveStaffDocumentTypeCommand(
                organization_id=ORG, name="Medical", alert_lead_days=(30,), actor=admin()
            ),
            uow=self.uow,
        )
        old = await self.record(expires_on=date(2026, 10, 10))
        with self.assertRaises(DomainError):
            await self.record(type_id=medical.id, replaces_id=old.id)

    async def test_update_changes_fields(self) -> None:
        doc = await self.record(expires_on=date(2026, 10, 10))
        updated = await self.service.update_document(
            UpdateStaffDocumentCommand(
                document_id=doc.id, changes={"expires_on": date(2027, 10, 10)}, actor=admin()
            ),
            uow=self.uow,
        )
        self.assertEqual(updated.status, "valid")

    async def test_due_alerts_are_collected_then_marked(self) -> None:
        doc = await self.record(expires_on=date(2026, 10, 5))
        alerts = await self.service.collect_due_expiry_alerts(uow=self.uow)
        self.assertEqual([(a.document_id, a.threshold_days) for a in alerts], [(doc.id, 7)])
        self.assertEqual(alerts[0].staff_name, "Amina Warsame")
        await self.service.mark_expiry_alerted(doc.id, 7, uow=self.uow)
        self.assertEqual(await self.service.collect_due_expiry_alerts(uow=self.uow), [])

    async def test_no_alerts_for_someone_who_has_left(self) -> None:
        await self.record(expires_on=date(2026, 10, 5))
        await self.service.change_status(
            ChangeTransportStaffStatusCommand(staff_id=self.staff.id, status="left", actor=admin()),
            uow=self.uow,
        )
        self.assertEqual(await self.service.collect_due_expiry_alerts(uow=self.uow), [])

    async def test_filter_by_status(self) -> None:
        await self.register(full_name="Second")
        page = await self.service.list_staff(
            ListTransportStaffQuery(
                page_request=OffsetPageRequest(page=1, page_size=20),
                filters=[FilterCondition(field="status", op="eq", value="active")],
            ),
            uow=self.uow,
        )
        self.assertEqual(page.total, 2)


if __name__ == "__main__":
    unittest.main()
