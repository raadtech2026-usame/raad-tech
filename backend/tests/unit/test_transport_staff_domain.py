"""Domain rules for transport staff, bus crew assignments and staff documents
(ADR-0049, ADR-0050, ADR-0051)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from raad.core.errors.exceptions import ConflictError, DomainError
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain.entities import (
    StaffDocument,
    StaffDocumentType,
    TransportStaff,
    TransportStaffRole,
    VehicleStaffAssignment,
)
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    PhoneNumber,
    StaffAssignmentKind,
    StaffDocumentId,
    StaffDocumentStatus,
    StaffDocumentTypeId,
    TransportStaffId,
    TransportStaffRoleId,
    TransportStaffStatus,
    VehicleId,
    VehicleStaffAssignmentId,
)

ORG = OrganizationId("01J8Z3K9G6X8YV5T4N2R7QW3MD")
STAFF = TransportStaffId("01J8Z3K9G6X8YV5T4N2R7QW3SA")
VEHICLE = VehicleId("01J8Z3K9G6X8YV5T4N2R7QW3VA")


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 9, 30, 8, tzinfo=timezone.utc))
TODAY = date(2026, 9, 30)


def _staff(**overrides) -> TransportStaff:
    values = dict(
        id=STAFF,
        organization_id=ORG,
        full_name="Amina Warsame",
        phone=PhoneNumber("+252611234567"),
        clock=CLOCK,
        actor_id="admin-1",
    )
    values.update(overrides)
    return TransportStaff.register(**values)


def _assignment(**overrides) -> VehicleStaffAssignment:
    values = dict(
        id=VehicleStaffAssignmentId("01J8Z3K9G6X8YV5T4N2R7QW3AA"),
        organization_id=ORG,
        staff_id=STAFF,
        vehicle_id=VEHICLE,
        role_id=None,
        route_id=None,
        starts_on=date(2026, 9, 1),
        ends_on=None,
        kind=StaffAssignmentKind.PERMANENT,
        reason=None,
        clock=CLOCK,
    )
    values.update(overrides)
    return VehicleStaffAssignment.assign(**values)


def _document(**overrides) -> StaffDocument:
    values = dict(
        id=StaffDocumentId("01J8Z3K9G6X8YV5T4N2R7QW3DA"),
        organization_id=ORG,
        staff_id=STAFF,
        type_id=StaffDocumentTypeId("01J8Z3K9G6X8YV5T4N2R7QW3TA"),
        number="DL-1",
        issued_on=date(2021, 1, 1),
        expires_on=date(2026, 12, 31),
        notes=None,
        replaces_id=None,
        clock=CLOCK,
    )
    values.update(overrides)
    return StaffDocument.record(**values)


class TransportStaffTests(unittest.TestCase):
    def test_register_starts_active_and_keeps_personal_data_out_of_the_event(self) -> None:
        staff = _staff(emergency_contact_name="Hodan", notes="Allergic to dust")
        self.assertIs(staff.status, TransportStaffStatus.ACTIVE)
        (event,) = staff.pull_domain_events()
        self.assertEqual(event.event_type, "TransportStaffRegistered")
        rendered = repr(event.payload)
        for private in ("Amina", "+2526", "Hodan", "Allergic"):
            self.assertNotIn(private, rendered)

    def test_blank_name_is_rejected(self) -> None:
        with self.assertRaises(DomainError):
            _staff(full_name="   ")

    def test_update_profile_names_changed_fields_only(self) -> None:
        staff = _staff()
        staff.pull_domain_events()
        staff.update_profile(clock=CLOCK, full_name="Amina W.", employee_ref=None)
        (event,) = staff.pull_domain_events()
        self.assertEqual(event.payload["changed_fields"], ["full_name"])
        self.assertEqual(staff.full_name, "Amina W.")

    def test_update_profile_with_no_change_records_nothing(self) -> None:
        staff = _staff()
        staff.pull_domain_events()
        staff.update_profile(clock=CLOCK, full_name="Amina Warsame")
        self.assertEqual(staff.pull_domain_events(), [])

    def test_update_profile_rejects_unknown_fields(self) -> None:
        with self.assertRaises(DomainError):
            _staff().update_profile(clock=CLOCK, status="left")

    def test_leaving_records_the_day_and_returning_clears_it(self) -> None:
        staff = _staff()
        self.assertTrue(staff.change_status(TransportStaffStatus.LEFT, clock=CLOCK))
        self.assertEqual(staff.left_on, TODAY)
        self.assertFalse(staff.change_status(TransportStaffStatus.LEFT, clock=CLOCK))
        staff.change_status(TransportStaffStatus.ACTIVE, clock=CLOCK)
        self.assertIsNone(staff.left_on)


class TransportStaffRoleTests(unittest.TestCase):
    def test_create_and_update_record_events_and_skip_no_ops(self) -> None:
        role = TransportStaffRole.create(
            id=TransportStaffRoleId("01J8Z3K9G6X8YV5T4N2R7QW3RA"),
            organization_id=ORG,
            name="Attendant",
            sort_order=10,
            clock=CLOCK,
        )
        self.assertEqual(role.pull_domain_events()[0].event_type, "TransportStaffRoleCreated")
        role.update(name="Attendant", sort_order=10, is_archived=False, clock=CLOCK)
        self.assertEqual(role.pull_domain_events(), [])
        role.update(name="Attendant", sort_order=10, is_archived=True, clock=CLOCK)
        self.assertEqual(role.pull_domain_events()[0].event_type, "TransportStaffRoleUpdated")


class VehicleStaffAssignmentTests(unittest.TestCase):
    def test_temporary_assignment_needs_an_end_date(self) -> None:
        with self.assertRaises(DomainError):
            _assignment(kind=StaffAssignmentKind.TEMPORARY, ends_on=None)

    def test_cannot_end_before_it_starts(self) -> None:
        with self.assertRaises(DomainError):
            _assignment(ends_on=date(2026, 8, 31))

    def test_is_current_and_overlaps(self) -> None:
        a = _assignment(ends_on=date(2026, 9, 30))
        self.assertTrue(a.is_current(TODAY))
        self.assertFalse(a.is_current(date(2026, 10, 1)))
        self.assertTrue(a.overlaps(date(2026, 9, 30), None))
        self.assertFalse(a.overlaps(date(2026, 10, 1), None))
        self.assertTrue(_assignment().overlaps(date(2030, 1, 1), date(2030, 1, 2)))

    def test_end_never_extends_and_is_idempotent(self) -> None:
        a = _assignment(ends_on=date(2026, 9, 15))
        self.assertFalse(a.end(TODAY, clock=CLOCK))
        self.assertEqual(a.ends_on, date(2026, 9, 15))
        b = _assignment()
        self.assertTrue(b.end(TODAY, clock=CLOCK))
        self.assertEqual(b.ends_on, TODAY)
        self.assertFalse(b.end(TODAY, clock=CLOCK))

    def test_ending_a_future_assignment_closes_it_before_it_starts(self) -> None:
        future = _assignment(starts_on=date(2026, 11, 1))
        future.end(TODAY, clock=CLOCK)
        self.assertEqual(future.ends_on, date(2026, 10, 31))
        self.assertFalse(future.is_current(date(2026, 11, 1)))


class StaffDocumentTypeTests(unittest.TestCase):
    def test_lead_days_are_deduplicated_sorted_and_bounded(self) -> None:
        doc_type = StaffDocumentType.create(
            id=StaffDocumentTypeId("01J8Z3K9G6X8YV5T4N2R7QW3TA"),
            organization_id=ORG,
            name="Driving licence",
            alert_lead_days=(7, 30, 7),
            clock=CLOCK,
        )
        self.assertEqual(doc_type.alert_lead_days, (30, 7))
        for bad in ((0,), (366,), (1, 2, 3, 4, 5, 6)):
            with self.assertRaises(DomainError):
                doc_type.update(
                    name="Driving licence", alert_lead_days=bad, is_archived=False, clock=CLOCK
                )


class StaffDocumentTests(unittest.TestCase):
    LEAD = (30, 7)

    def test_status_follows_the_dates(self) -> None:
        cases = {
            date(2026, 12, 31): StaffDocumentStatus.VALID,
            date(2026, 10, 30): StaffDocumentStatus.EXPIRING,
            TODAY: StaffDocumentStatus.EXPIRING,
            date(2026, 9, 29): StaffDocumentStatus.EXPIRED,
        }
        for expires_on, expected in cases.items():
            with self.subTest(expires_on=expires_on):
                self.assertIs(_document(expires_on=expires_on).status(TODAY, self.LEAD), expected)
        self.assertIs(
            _document(expires_on=None).status(TODAY, self.LEAD), StaffDocumentStatus.NO_EXPIRY
        )

    def test_expiry_before_issue_is_rejected(self) -> None:
        with self.assertRaises(DomainError):
            _document(issued_on=date(2027, 1, 1), expires_on=date(2026, 1, 1))

    def test_each_threshold_is_alerted_exactly_once(self) -> None:
        doc = _document(expires_on=date(2026, 10, 30))  # 30 days left
        self.assertEqual(doc.due_alert_threshold(TODAY, self.LEAD), 30)
        doc.mark_alerted(30, clock=CLOCK)
        self.assertIsNone(doc.due_alert_threshold(TODAY, self.LEAD))
        self.assertIsNone(doc.due_alert_threshold(date(2026, 10, 20), self.LEAD))
        self.assertEqual(doc.due_alert_threshold(date(2026, 10, 23), self.LEAD), 7)
        doc.mark_alerted(7, clock=CLOCK)
        self.assertEqual(doc.due_alert_threshold(date(2026, 10, 30), self.LEAD), 0)
        doc.mark_alerted(0, clock=CLOCK)
        self.assertIsNone(doc.due_alert_threshold(date(2026, 12, 1), self.LEAD))

    def test_a_document_found_already_expired_sends_one_alert_not_a_burst(self) -> None:
        doc = _document(issued_on=None, expires_on=date(2026, 1, 1))
        self.assertEqual(doc.due_alert_threshold(TODAY, self.LEAD), 0)

    def test_changing_the_expiry_restarts_the_alerts(self) -> None:
        doc = _document(expires_on=date(2026, 10, 1))
        doc.mark_alerted(7, clock=CLOCK)
        doc.update(clock=CLOCK, expires_on=date(2026, 10, 20))
        self.assertIsNone(doc.alerted_threshold_days)
        self.assertEqual(doc.due_alert_threshold(TODAY, self.LEAD), 30)

    def test_a_renewed_document_is_superseded_and_never_alerts(self) -> None:
        doc = _document(expires_on=date(2026, 10, 1))
        doc.mark_replaced(StaffDocumentId("01J8Z3K9G6X8YV5T4N2R7QW3DB"), clock=CLOCK)
        self.assertIs(doc.status(TODAY, self.LEAD), StaffDocumentStatus.SUPERSEDED)
        self.assertIsNone(doc.due_alert_threshold(TODAY, self.LEAD))
        with self.assertRaises(ConflictError):
            doc.mark_replaced(StaffDocumentId("01J8Z3K9G6X8YV5T4N2R7QW3DC"), clock=CLOCK)

    def test_events_carry_no_document_number(self) -> None:
        doc = _document(number="SECRET-123")
        doc.update(clock=CLOCK, number="SECRET-456")
        for event in doc.pull_domain_events():
            self.assertNotIn("SECRET", repr(event.payload))


if __name__ == "__main__":
    unittest.main()
