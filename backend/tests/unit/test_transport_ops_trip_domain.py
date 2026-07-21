"""Domain-only tests for `transport_ops`'s `Trip` aggregate (Phase 12). Stdlib `unittest` — no
`pytest` (not an approved dependency), mirroring `test_transport_ops_route_domain.py`'s
established precedent exactly. Covers: value-object validation (`TripId`/`VehicleId`),
construction, `schedule()` (incl. cross-organization rejection), the full documented lifecycle
state machine (Phase-2 §6.2) — every legal transition and every illegal one
(`RuleViolationError`), `interrupt`/`resume` legality, `change_driver` (incl. cross-organization
rejection and idempotent same-driver no-op), domain-event emission, and repository-interface
shape.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from raad.core.errors.exceptions import DomainError, RuleViolationError
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain.entities import Trip
from raad.modules.transport_ops.domain.repositories import TripRepository
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    OrganizationId,
    RouteId,
    TripId,
    TripStatus,
    TripType,
    VehicleId,
)

VALID_TRIP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3TR"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ZY"
VALID_VEHICLE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3VE"
VALID_DRIVER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3DR"
OTHER_DRIVER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3D2"
VALID_ROUTE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3RT"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def make_trip(**overrides) -> Trip:
    defaults = dict(
        id=TripId(VALID_TRIP_ULID),
        organization_id=OrganizationId(VALID_ORG_ULID),
        vehicle_id=VehicleId(VALID_VEHICLE_ULID),
        driver_id=DriverId(VALID_DRIVER_ULID),
        route_id=RouteId(VALID_ROUTE_ULID),
        trip_type=TripType.MORNING,
        status=TripStatus.SCHEDULED,
        scheduled_date=date(2026, 7, 20),
        started_at=None,
        ended_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Trip(**defaults)


class TripIdValidationTests(unittest.TestCase):
    def test_valid_ulid_constructs(self) -> None:
        trip_id = TripId(VALID_TRIP_ULID)
        self.assertEqual(str(trip_id), VALID_TRIP_ULID)

    def test_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            TripId("TOOSHORT")

    def test_lowercase_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            TripId(VALID_TRIP_ULID.lower())

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            TripId("")

    def test_equality_is_by_value(self) -> None:
        self.assertEqual(TripId(VALID_TRIP_ULID), TripId(VALID_TRIP_ULID))


class VehicleIdValidationTests(unittest.TestCase):
    """`VehicleId` is a cross-module reference (opaque, no existence check — see
    `domain/value_objects.py`'s Phase 12 addition) so, unlike `TripId`, only non-emptiness is
    validated, mirroring `OrganizationId`'s identical treatment."""

    def test_non_empty_string_constructs(self) -> None:
        vehicle_id = VehicleId(VALID_VEHICLE_ULID)
        self.assertEqual(str(vehicle_id), VALID_VEHICLE_ULID)

    def test_arbitrary_non_ulid_string_is_accepted(self) -> None:
        # Cross-module ids are never re-validated against another module's own id format
        # (`.claude/rules/database.md` #3) - confirms this is not accidentally ULID-checked.
        vehicle_id = VehicleId("some-opaque-vehicle-ref")
        self.assertEqual(str(vehicle_id), "some-opaque-vehicle-ref")

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            VehicleId("")

    def test_equality_is_by_value(self) -> None:
        self.assertEqual(VehicleId(VALID_VEHICLE_ULID), VehicleId(VALID_VEHICLE_ULID))


class TripConstructionTests(unittest.TestCase):
    def test_valid_trip_constructs(self) -> None:
        trip = make_trip()
        self.assertEqual(trip.status, TripStatus.SCHEDULED)
        self.assertEqual(trip.trip_type, TripType.MORNING)
        self.assertIsNone(trip.started_at)
        self.assertIsNone(trip.ended_at)

    def test_equality_is_by_id_not_by_field_values(self) -> None:
        a = make_trip(trip_type=TripType.MORNING)
        b = make_trip(trip_type=TripType.AFTERNOON)  # same id, different field
        self.assertEqual(a, b)

    def test_inequality_across_different_ids(self) -> None:
        other_id = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"
        a = make_trip()
        b = make_trip(id=TripId(other_id))
        self.assertNotEqual(a, b)

    def test_hash_matches_id_hash(self) -> None:
        trip = make_trip()
        self.assertEqual(hash(trip), hash(trip.id))


class TripScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc))

    def test_schedule_starts_scheduled(self) -> None:
        trip = Trip.schedule(
            id=TripId(VALID_TRIP_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            driver_id=DriverId(VALID_DRIVER_ULID),
            driver_organization_id=OrganizationId(VALID_ORG_ULID),
            route_id=RouteId(VALID_ROUTE_ULID),
            route_organization_id=OrganizationId(VALID_ORG_ULID),
            trip_type=TripType.MORNING,
            scheduled_date=date(2026, 7, 20),
            clock=self.clock,
        )
        self.assertEqual(trip.status, TripStatus.SCHEDULED)
        self.assertIsNone(trip.started_at)
        self.assertIsNone(trip.ended_at)

    def test_schedule_records_trip_scheduled_event(self) -> None:
        trip = Trip.schedule(
            id=TripId(VALID_TRIP_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            driver_id=DriverId(VALID_DRIVER_ULID),
            driver_organization_id=OrganizationId(VALID_ORG_ULID),
            route_id=RouteId(VALID_ROUTE_ULID),
            route_organization_id=OrganizationId(VALID_ORG_ULID),
            trip_type=TripType.MORNING,
            scheduled_date=date(2026, 7, 20),
            clock=self.clock,
            actor_id="admin-1",
        )
        events = trip.pull_domain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "TripScheduled")
        self.assertEqual(event.aggregate_type, "Trip")
        self.assertEqual(event.aggregate_id, VALID_TRIP_ULID)
        self.assertEqual(event.org_id, VALID_ORG_ULID)
        self.assertEqual(event.occurred_at, self.clock.now())
        self.assertEqual(event.payload["vehicle_id"], VALID_VEHICLE_ULID)
        self.assertEqual(event.payload["driver_id"], VALID_DRIVER_ULID)
        self.assertEqual(event.payload["route_id"], VALID_ROUTE_ULID)
        self.assertEqual(event.payload["trip_type"], "morning")
        self.assertEqual(event.payload["scheduled_date"], "2026-07-20")
        self.assertEqual(event.payload["actor_id"], "admin-1")

    def test_schedule_rejects_cross_organization_driver(self) -> None:
        with self.assertRaises(DomainError):
            Trip.schedule(
                id=TripId(VALID_TRIP_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                vehicle_id=VehicleId(VALID_VEHICLE_ULID),
                driver_id=DriverId(VALID_DRIVER_ULID),
                driver_organization_id=OrganizationId(OTHER_ORG_ULID),
                route_id=RouteId(VALID_ROUTE_ULID),
                route_organization_id=OrganizationId(VALID_ORG_ULID),
                trip_type=TripType.MORNING,
                scheduled_date=date(2026, 7, 20),
                clock=self.clock,
            )

    def test_schedule_rejects_cross_organization_route(self) -> None:
        with self.assertRaises(DomainError):
            Trip.schedule(
                id=TripId(VALID_TRIP_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                vehicle_id=VehicleId(VALID_VEHICLE_ULID),
                driver_id=DriverId(VALID_DRIVER_ULID),
                driver_organization_id=OrganizationId(VALID_ORG_ULID),
                route_id=RouteId(VALID_ROUTE_ULID),
                route_organization_id=OrganizationId(OTHER_ORG_ULID),
                trip_type=TripType.MORNING,
                scheduled_date=date(2026, 7, 20),
                clock=self.clock,
            )


class TripLifecycleStateMachineTests(unittest.TestCase):
    """Phase-2 §6.2's documented state diagram, exhaustively: every legal edge succeeds, every
    other current-status combination raises `RuleViolationError`."""

    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc))

    # --- start(): Scheduled -> InProgress ---

    def test_start_from_scheduled_succeeds(self) -> None:
        trip = make_trip(status=TripStatus.SCHEDULED)
        trip.start(clock=self.clock, actor_id="driver-1")
        self.assertEqual(trip.status, TripStatus.IN_PROGRESS)
        self.assertEqual(trip.started_at, self.clock.now())
        events = trip.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "TripStarted")

    def test_start_from_in_progress_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.IN_PROGRESS)
        with self.assertRaises(RuleViolationError):
            trip.start(clock=self.clock)

    def test_start_from_interrupted_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.INTERRUPTED)
        with self.assertRaises(RuleViolationError):
            trip.start(clock=self.clock)

    def test_start_from_completed_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.COMPLETED)
        with self.assertRaises(RuleViolationError):
            trip.start(clock=self.clock)

    # --- end(): InProgress -> Completed, Interrupted -> Completed ---

    def test_end_from_in_progress_succeeds(self) -> None:
        trip = make_trip(status=TripStatus.IN_PROGRESS)
        trip.end(clock=self.clock, actor_id="driver-1")
        self.assertEqual(trip.status, TripStatus.COMPLETED)
        self.assertEqual(trip.ended_at, self.clock.now())
        events = trip.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "TripEnded")

    def test_end_from_interrupted_succeeds(self) -> None:
        trip = make_trip(status=TripStatus.INTERRUPTED)
        trip.end(clock=self.clock)
        self.assertEqual(trip.status, TripStatus.COMPLETED)

    def test_end_from_scheduled_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.SCHEDULED)
        with self.assertRaises(RuleViolationError):
            trip.end(clock=self.clock)

    def test_end_from_completed_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.COMPLETED)
        with self.assertRaises(RuleViolationError):
            trip.end(clock=self.clock)

    # --- interrupt(): InProgress -> Interrupted ---

    def test_interrupt_from_in_progress_succeeds(self) -> None:
        trip = make_trip(status=TripStatus.IN_PROGRESS)
        trip.interrupt("device offline", clock=self.clock, actor_id="system")
        self.assertEqual(trip.status, TripStatus.INTERRUPTED)
        events = trip.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "TripInterrupted")
        self.assertEqual(events[0].payload["reason"], "device offline")

    def test_interrupt_from_scheduled_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.SCHEDULED)
        with self.assertRaises(RuleViolationError):
            trip.interrupt("timeout", clock=self.clock)

    def test_interrupt_from_interrupted_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.INTERRUPTED)
        with self.assertRaises(RuleViolationError):
            trip.interrupt("timeout", clock=self.clock)

    def test_interrupt_from_completed_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.COMPLETED)
        with self.assertRaises(RuleViolationError):
            trip.interrupt("timeout", clock=self.clock)

    def test_interrupt_with_empty_reason_raises_domain_error(self) -> None:
        trip = make_trip(status=TripStatus.IN_PROGRESS)
        with self.assertRaises(DomainError):
            trip.interrupt("", clock=self.clock)

    def test_interrupt_with_over_500_char_reason_raises_domain_error(self) -> None:
        trip = make_trip(status=TripStatus.IN_PROGRESS)
        with self.assertRaises(DomainError):
            trip.interrupt("x" * 501, clock=self.clock)

    # --- resume(): Interrupted -> InProgress ---

    def test_resume_from_interrupted_succeeds(self) -> None:
        trip = make_trip(status=TripStatus.INTERRUPTED)
        trip.resume(clock=self.clock, actor_id="driver-1")
        self.assertEqual(trip.status, TripStatus.IN_PROGRESS)
        events = trip.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "TripResumed")

    def test_resume_from_scheduled_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.SCHEDULED)
        with self.assertRaises(RuleViolationError):
            trip.resume(clock=self.clock)

    def test_resume_from_in_progress_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.IN_PROGRESS)
        with self.assertRaises(RuleViolationError):
            trip.resume(clock=self.clock)

    def test_resume_from_completed_raises_rule_violation_error(self) -> None:
        trip = make_trip(status=TripStatus.COMPLETED)
        with self.assertRaises(RuleViolationError):
            trip.resume(clock=self.clock)


class TripChangeDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc))

    def test_change_driver_updates_driver_id_and_records_event(self) -> None:
        trip = make_trip(driver_id=DriverId(VALID_DRIVER_ULID))
        trip.change_driver(
            DriverId(OTHER_DRIVER_ULID),
            new_driver_organization_id=OrganizationId(VALID_ORG_ULID),
            clock=self.clock,
            actor_id="admin-1",
        )
        self.assertEqual(trip.driver_id, DriverId(OTHER_DRIVER_ULID))
        events = trip.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "TripDriverChanged")
        self.assertEqual(events[0].payload["driver_id"], OTHER_DRIVER_ULID)

    def test_change_driver_to_same_driver_is_idempotent_no_op(self) -> None:
        trip = make_trip(driver_id=DriverId(VALID_DRIVER_ULID))
        trip.change_driver(
            DriverId(VALID_DRIVER_ULID),
            new_driver_organization_id=OrganizationId(VALID_ORG_ULID),
            clock=self.clock,
        )
        self.assertEqual(trip.pull_domain_events(), [])

    def test_change_driver_rejects_cross_organization_driver(self) -> None:
        trip = make_trip()
        with self.assertRaises(DomainError):
            trip.change_driver(
                DriverId(OTHER_DRIVER_ULID),
                new_driver_organization_id=OrganizationId(OTHER_ORG_ULID),
                clock=self.clock,
            )

    def test_change_driver_allowed_regardless_of_status(self) -> None:
        # No approved document restricts this transition by status (`entities.py`'s
        # `Trip.change_driver` docstring) - confirm it works even on a COMPLETED trip.
        trip = make_trip(status=TripStatus.COMPLETED, driver_id=DriverId(VALID_DRIVER_ULID))
        trip.change_driver(
            DriverId(OTHER_DRIVER_ULID),
            new_driver_organization_id=OrganizationId(VALID_ORG_ULID),
            clock=self.clock,
        )
        self.assertEqual(trip.driver_id, DriverId(OTHER_DRIVER_ULID))


class TripRepositoryInterfaceShapeTests(unittest.TestCase):
    def test_trip_repository_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            TripRepository()  # type: ignore[abstract]

    def test_trip_repository_declares_expected_methods(self) -> None:
        for method_name in (
            "get",
            "add",
            "list_all",
            "active_trip_for_vehicle",
            "list_for_route",
        ):
            self.assertTrue(hasattr(TripRepository, method_name))


if __name__ == "__main__":
    unittest.main()
