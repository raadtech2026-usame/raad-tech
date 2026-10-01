"""Document requirements and compliance (ADR-0058) and their effect on daily operations (ADR-0059).

The persistence side (the two new columns, the scoped queries) is covered against PostgreSQL in
`tests/integration/test_document_compliance_repository.py`.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from raad.core.errors.exceptions import NotFoundError, RuleViolationError, ValidationError
from raad.modules.transport_ops.application.commands import (
    AssignStaffToVehicleCommand,
    CreateCoverCommand,
    SaveStaffDocumentTypeCommand,
    ScheduleTripCommand,
    StartTripCommand,
)
from raad.modules.transport_ops.application.staff_services import TransportStaffApplicationService
from raad.modules.transport_ops.domain.entities import StaffDocument, StaffDocumentType
from raad.modules.transport_ops.domain.services import staff_compliance
from raad.modules.transport_ops.domain.value_objects import (
    ComplianceStatus,
    OrganizationId,
    StaffDocumentEnforcement,
    StaffDocumentId,
    StaffDocumentRequirement,
    StaffDocumentTypeId,
    TransportStaffId,
    TransportStaffStatus,
)
from test_daily_operations import (
    ADMIN,
    BUS,
    BUS_2,
    CLOCK,
    ORG,
    OTHER_ORG,
    ROUTE,
    TODAY,
    OperationsTestCase,
    SequentialIds,
)

STAFF = TransportStaffId("01J8Z3K9G6X8YV5T4N2R7QW3SA")


def a_type(
    name="Driving licence",
    *,
    required_for=StaffDocumentRequirement.DRIVERS,
    enforcement=StaffDocumentEnforcement.WARN,
    organization=ORG,
    ident="01J8Z3K9G6X8YV5T4N2R7QW3TA",
) -> StaffDocumentType:
    return StaffDocumentType.create(
        id=StaffDocumentTypeId(ident),
        organization_id=OrganizationId(organization),
        name=name,
        required_for=required_for,
        enforcement=enforcement,
        clock=CLOCK,
    )


def a_document(doc_type, *, expires_on, staff_id=STAFF, ident="01J8Z3K9G6X8YV5T4N2R7QW3DA", number="SECRET-123"):
    return StaffDocument.record(
        id=StaffDocumentId(ident),
        organization_id=doc_type.organization_id,
        staff_id=staff_id,
        type_id=doc_type.id,
        number=number,
        issued_on=None,
        expires_on=expires_on,
        notes=None,
        replaces_id=None,
        clock=CLOCK,
    )


class ComplianceRuleTests(unittest.TestCase):
    def check(self, types, documents, *, is_driver=True, day=TODAY):
        return staff_compliance(is_driver=is_driver, types=types, documents=documents, day=day)

    def test_nothing_required_is_compliant(self) -> None:
        optional = a_type(required_for=StaffDocumentRequirement.NONE)
        self.assertIs(self.check([optional], []).status, ComplianceStatus.COMPLIANT)

    def test_a_driver_requirement_follows_driver_access_not_a_title(self) -> None:
        licence = a_type()
        self.assertIs(self.check([licence], [], is_driver=False).status, ComplianceStatus.COMPLIANT)
        result = self.check([licence], [], is_driver=True)
        self.assertIs(result.status, ComplianceStatus.NOT_COMPLIANT)
        self.assertEqual((result.gaps[0].reason, result.gaps[0].expired_on), ("missing", None))
        everyone = a_type(required_for=StaffDocumentRequirement.ALL_STAFF)
        self.assertIs(self.check([everyone], [], is_driver=False).status, ComplianceStatus.NOT_COMPLIANT)

    def test_a_document_is_valid_through_its_expiry_date(self) -> None:
        licence = a_type()
        document = a_document(licence, expires_on=TODAY)
        self.assertTrue(self.check([licence], [document], day=TODAY).is_compliant)
        lapsed = self.check([licence], [document], day=TODAY + timedelta(days=1))
        self.assertEqual((lapsed.gaps[0].reason, lapsed.gaps[0].expired_on), ("expired", TODAY))
        self.assertEqual(lapsed.describe_gaps(), f"Driving licence expired on {TODAY.isoformat()}")

    def test_no_expiry_date_always_meets_the_requirement(self) -> None:
        licence = a_type()
        self.assertIs(
            self.check([licence], [a_document(licence, expires_on=None)], day=date(2099, 1, 1)).status,
            ComplianceStatus.COMPLIANT,
        )

    def test_a_superseded_document_does_not_count_but_its_renewal_does(self) -> None:
        licence = a_type()
        old = a_document(licence, expires_on=TODAY + timedelta(days=400))
        old.mark_replaced(StaffDocumentId("01J8Z3K9G6X8YV5T4N2R7QW3DB"), clock=CLOCK)
        self.assertEqual(self.check([licence], [old]).gaps[0].reason, "missing")
        renewal = a_document(licence, expires_on=TODAY + timedelta(days=400), ident="01J8Z3K9G6X8YV5T4N2R7QW3DB")
        self.assertTrue(self.check([licence], [old, renewal]).is_compliant)

    def test_an_archived_type_requires_nothing(self) -> None:
        licence = a_type()
        licence.update(name=licence.name, alert_lead_days=(30, 7), is_archived=True, clock=CLOCK)
        self.assertIs(self.check([licence], []).status, ComplianceStatus.COMPLIANT)

    def test_expiring_is_still_compliant_and_uses_the_types_lead_days(self) -> None:
        licence = a_type()
        soon = self.check([licence], [a_document(licence, expires_on=TODAY + timedelta(days=30))])
        self.assertEqual((soon.status, soon.is_compliant), (ComplianceStatus.EXPIRING, True))
        later = self.check([licence], [a_document(licence, expires_on=TODAY + timedelta(days=31))])
        self.assertIs(later.status, ComplianceStatus.COMPLIANT)

    def test_only_a_block_type_blocks(self) -> None:
        warn = a_type()
        block = a_type("Medical certificate", enforcement=StaffDocumentEnforcement.BLOCK, ident="01J8Z3K9G6X8YV5T4N2R7QW3TB")
        result = self.check([warn, block], [])
        self.assertEqual([g.type_name for g in result.blocking_gaps], ["Medical certificate"])
        self.assertEqual(len(result.gaps), 2)

    def test_update_keeps_the_requirement_unless_told(self) -> None:
        licence = a_type(enforcement=StaffDocumentEnforcement.BLOCK)
        licence.pull_domain_events()
        licence.update(name="Licence", alert_lead_days=(30, 7), is_archived=False, clock=CLOCK)
        self.assertEqual(
            (licence.required_for, licence.enforcement),
            (StaffDocumentRequirement.DRIVERS, StaffDocumentEnforcement.BLOCK),
        )
        payload = licence.pull_domain_events()[-1].payload
        self.assertEqual((payload["required_for"], payload["enforcement"]), ("drivers", "block"))


class ComplianceCase(OperationsTestCase):
    """Amina and Hassan drive; Fatima is an attendant. Amina drives the timetabled bus."""

    def setUp(self) -> None:
        super().setUp()
        self.staff_service = TransportStaffApplicationService(
            clock=CLOCK, id_generator=self.ids, user_provisioning=None, vehicle_directory=self.vehicles
        )
        self._n = 0

    def require(self, name="Driving licence", *, required_for="drivers", enforcement="warn", organization=ORG):
        self._n += 1
        doc_type = a_type(
            name,
            required_for=StaffDocumentRequirement(required_for),
            enforcement=StaffDocumentEnforcement(enforcement),
            organization=organization,
            ident=f"01J8Z3K9G6X8YV5T4N2RTY{self._n:04d}",
        )
        self.uow.staff_document_types.add(doc_type)
        return doc_type

    def hold(self, person, doc_type, expires_on):
        self._n += 1
        document = a_document(doc_type, expires_on=expires_on, staff_id=person[0].id, ident=f"01J8Z3K9G6X8YV5T4N2RDC{self._n:04d}")
        self.uow.staff_documents.add(document)
        return document


class StaffComplianceServiceTests(ComplianceCase):
    async def test_a_type_is_saved_with_its_requirement_and_bad_values_are_refused(self) -> None:
        created = await self.staff_service.save_document_type(
            SaveStaffDocumentTypeCommand(
                organization_id=ORG, name="Driving licence", alert_lead_days=(30, 7), actor=ADMIN,
                required_for="drivers", enforcement="block",
            ),
            uow=self.uow,
        )
        self.assertEqual((created.required_for, created.enforcement), ("drivers", "block"))
        kept = await self.staff_service.save_document_type(
            SaveStaffDocumentTypeCommand(
                organization_id=ORG, name="Licence", alert_lead_days=(30, 7), actor=ADMIN, type_id=created.id
            ),
            uow=self.uow,
        )
        self.assertEqual((kept.name, kept.required_for, kept.enforcement), ("Licence", "drivers", "block"))
        plain = await self.staff_service.save_document_type(
            SaveStaffDocumentTypeCommand(organization_id=ORG, name="Other", alert_lead_days=(30,), actor=ADMIN),
            uow=self.uow,
        )
        self.assertEqual((plain.required_for, plain.enforcement), ("none", "warn"))
        with self.assertRaises(ValidationError):
            await self.staff_service.save_document_type(
                SaveStaffDocumentTypeCommand(
                    organization_id=ORG, name="X", alert_lead_days=(30,), actor=ADMIN, required_for="teachers"
                ),
                uow=self.uow,
            )

    async def test_impact_counts_who_it_applies_to_and_who_falls_short_today(self) -> None:
        licence = self.require(required_for="none")
        self.hold(self.amina, licence, TODAY + timedelta(days=90))
        self.hold(self.hassan, licence, TODAY - timedelta(days=1))
        for required_for, expected in (("drivers", (2, 1)), ("all_staff", (3, 2)), ("none", (0, 0))):
            with self.subTest(required_for=required_for):
                impact = await self.staff_service.document_type_impact(str(licence.id), required_for, uow=self.uow)
                self.assertEqual((impact.applies_to, impact.not_compliant), expected)
        with self.assertRaises(NotFoundError):
            await self.staff_service.document_type_impact("01J8Z3K9G6X8YV5T4N2R7QW3ZZ", "drivers", uow=self.uow)

    async def test_the_compliance_list_is_worst_first_and_skips_the_compliant_and_the_departed(self) -> None:
        licence = self.require()
        self.hold(self.amina, licence, TODAY + timedelta(days=5))   # expiring
        self.hold(self.hassan, licence, TODAY - timedelta(days=3))  # expired
        gone = self.person("Zed Driver", driver=True)                # would be missing
        gone[0].change_status(TransportStaffStatus.LEFT, clock=CLOCK)
        rows = await self.staff_service.list_staff_compliance(uow=self.uow)
        self.assertEqual(
            [(r.staff_name, r.compliance.status) for r in rows],
            [("Hassan Driver", "not_compliant"), ("Amina Driver", "expiring")],
        )
        self.assertEqual(rows[0].compliance.gaps[0].reason, "expired")
        self.assertNotIn("SECRET-123", repr(rows))

    async def test_nothing_required_means_an_empty_list_and_compliant_records(self) -> None:
        self.assertEqual(await self.staff_service.list_staff_compliance(uow=self.uow), [])
        record = await self.staff_service.get_staff(str(self.amina[0].id), uow=self.uow)
        self.assertEqual((record.compliance.status, record.compliance.gaps), ("compliant", []))

    async def test_a_staff_record_and_the_list_carry_status_and_reasons_never_a_number(self) -> None:
        self.require("Medical certificate", required_for="all_staff", enforcement="block")
        record = await self.staff_service.get_staff(str(self.fatima[0].id), uow=self.uow)
        self.assertEqual((record.compliance.status, record.compliance.is_blocked), ("not_compliant", True))
        self.assertEqual(record.compliance.gaps[0].type_name, "Medical certificate")

    async def test_another_organizations_requirement_does_not_apply(self) -> None:
        self.require(organization=OTHER_ORG)
        record = await self.staff_service.get_staff(str(self.amina[0].id), uow=self.uow)
        self.assertEqual(record.compliance.status, "compliant")


class ComplianceInOperationsTests(ComplianceCase):
    async def asyncSetUp(self) -> None:
        await self.timetable()
        await self.generate(days=7)

    def trip_on(self, day):
        return next(t for t in self.uow.trips.by_id.values() if t.scheduled_date == day)

    async def test_a_non_compliant_driver_makes_the_trip_uncovered_on_the_board_and_in_alerts(self) -> None:
        board = await self.service.daily_board(TODAY, uow=self.uow)
        self.assertEqual(board.uncovered_trips, 0)
        self.require()
        board = await self.service.daily_board(TODAY, uow=self.uow)
        self.assertEqual(
            (board.uncovered_trips, board.vehicles[0].trips[0].uncovered_reason), (1, "driver_not_compliant")
        )
        alerts = await self.service.collect_uncovered_alerts(uow=self.uow)
        self.assertTrue(alerts and all(a.reason == "driver_not_compliant" for a in alerts))
        self.assertEqual(await self.service.uncovered_today(uow=self.uow), {ORG: 1})

    async def test_a_lapse_flags_only_the_trips_after_the_expiry_date(self) -> None:
        licence = self.require()
        self.hold(self.amina, licence, TODAY + timedelta(days=1))
        today = await self.service.daily_board(TODAY, uow=self.uow)
        tomorrow = await self.service.daily_board(TODAY + timedelta(days=1), uow=self.uow)
        after = await self.service.daily_board(TODAY + timedelta(days=2), uow=self.uow)
        self.assertEqual(
            [b.vehicles[0].trips[0].uncovered_reason for b in (today, tomorrow, after)],
            [None, None, "driver_not_compliant"],
        )

    async def test_generation_still_creates_the_trip_and_the_preview_says_why_it_is_uncovered(self) -> None:
        licence = self.require()
        self.hold(self.amina, licence, TODAY + timedelta(days=1))
        self.uow.trips.by_id.clear()
        preview = await self.generate(days=7, dry_run=True)
        reasons = {p.scheduled_date: p.uncovered_reason for p in preview.to_create}
        self.assertEqual(len(preview.to_create), 5)
        self.assertIsNone(reasons[TODAY])
        self.assertEqual(reasons[TODAY + timedelta(days=2)], "driver_not_compliant")
        created = await self.generate(days=7)
        self.assertEqual(created.created, 5)

    async def test_crew_get_a_badge_and_never_change_coverage(self) -> None:
        self.require("First-aid certificate", required_for="all_staff")
        licence_holder = self.require("Other", required_for="none")
        self.hold(self.amina, licence_holder, None)
        await self.staff_service.assign_to_vehicle(
            AssignStaffToVehicleCommand(staff_id=str(self.fatima[0].id), vehicle_id=BUS, kind="permanent", actor=ADMIN),
            uow=self.uow,
        )
        board = await self.service.daily_board(TODAY, uow=self.uow)
        crew = {c.staff_name: c.compliance_status for c in board.vehicles[0].crew}
        self.assertEqual(crew["Fatima Attendant"], "not_compliant")
        self.assertEqual(board.vehicles[0].crew_gaps, 0)
        # Amina drives and also lacks the certificate, so her trip is uncovered; Fatima adds nothing.
        self.assertEqual(board.uncovered_trips, 1)

    async def test_crew_assignment_warns_even_for_a_block_type(self) -> None:
        self.require("Medical certificate", required_for="all_staff", enforcement="block")
        assignment = await self.staff_service.assign_to_vehicle(
            AssignStaffToVehicleCommand(staff_id=str(self.fatima[0].id), vehicle_id=BUS, kind="permanent", actor=ADMIN),
            uow=self.uow,
        )
        self.assertEqual(len(assignment.warnings), 1)
        self.assertIn("Medical certificate missing", assignment.warnings[0])

    async def test_a_substitute_is_warned_about_or_refused_on_any_day_of_the_cover(self) -> None:
        licence = self.require()
        self.hold(self.amina, licence, None)
        self.hold(self.hassan, licence, TODAY + timedelta(days=1))  # lapses inside the three-day cover
        absence = await self.unavailable(self.amina[0])
        command = CreateCoverCommand(
            unavailability_id=absence.id, substitute_staff_id=str(self.hassan[0].id), vehicle_id=BUS, actor=ADMIN
        )
        licence.update(name=licence.name, alert_lead_days=(30, 7), is_archived=False, clock=CLOCK,
                       enforcement=StaffDocumentEnforcement.BLOCK)
        covers_before = len(self.uow.covers.by_id)
        with self.assertRaises(RuleViolationError) as refused:
            await self.service.create_cover(command, uow=self.uow)
        self.assertIn("Driving licence expired", str(refused.exception))
        self.assertEqual(len(self.uow.covers.by_id), covers_before)
        self.assertEqual(self.trip_on(TODAY).driver_id, self.amina[1].id)

        licence.update(name=licence.name, alert_lead_days=(30, 7), is_archived=False, clock=CLOCK,
                       enforcement=StaffDocumentEnforcement.WARN)
        cover = await self.service.create_cover(command, uow=self.uow)
        self.assertTrue(any("not compliant" in w for w in cover.warnings))
        # The substitute now drives, and the day after the licence lapses is flagged.
        board = await self.service.daily_board(TODAY + timedelta(days=2), uow=self.uow)
        self.assertEqual(board.vehicles[0].trips[0].uncovered_reason, "driver_not_compliant")

    async def test_a_timetable_driver_is_refused_only_when_set_or_changed(self) -> None:
        licence = self.require(enforcement="block")
        self.hold(self.amina, licence, None)
        with self.assertRaises(RuleViolationError):
            await self.timetable(vehicle_id=BUS_2, default_driver_id=str(self.hassan[1].id))
        entry = (await self.service.list_timetable(uow=self.uow))[0]
        self.uow.staff_documents.by_id.clear()  # Amina's licence is now missing too
        saved = await self.timetable(entry_id=entry.id, planned_departure=None)
        self.assertEqual(len(saved.warnings), 1)
        with self.assertRaises(RuleViolationError):
            await self.timetable(entry_id=entry.id, default_driver_id=str(self.hassan[1].id))

    async def test_a_manual_trip_warns_or_is_refused_on_its_own_date(self) -> None:
        licence = self.require()
        self.hold(self.hassan, licence, TODAY + timedelta(days=1))

        def command(day):
            return ScheduleTripCommand(
                organization_id=ORG, vehicle_id=BUS_2, driver_id=str(self.hassan[1].id), route_id=ROUTE,
                trip_type="afternoon", scheduled_date=day, actor=ADMIN,
            )

        fine = await self.trip_service.schedule_trip(command(TODAY), uow=self.uow)
        self.assertEqual(fine.warnings, [])
        warned = await self.trip_service.schedule_trip(command(TODAY + timedelta(days=2)), uow=self.uow)
        self.assertIn("Driving licence expired", warned.warnings[0])
        licence.update(name=licence.name, alert_lead_days=(30, 7), is_archived=False, clock=CLOCK,
                       enforcement=StaffDocumentEnforcement.BLOCK)
        trips_before = len(self.uow.trips.by_id)
        with self.assertRaises(RuleViolationError):
            await self.trip_service.schedule_trip(command(TODAY + timedelta(days=3)), uow=self.uow)
        self.assertEqual(len(self.uow.trips.by_id), trips_before)

    async def test_starting_a_scheduled_trip_is_never_blocked(self) -> None:
        self.require(enforcement="block")
        trip = self.trip_on(TODAY)
        started = await self.trip_service.start_trip(
            StartTripCommand(trip_id=str(trip.id), actor=ADMIN), uow=self.uow
        )
        self.assertEqual(started.status, "in_progress")
        board = await self.service.daily_board(TODAY, uow=self.uow)
        self.assertEqual(board.vehicles[0].trips[0].uncovered_reason, "driver_not_compliant")


if __name__ == "__main__":
    unittest.main()
