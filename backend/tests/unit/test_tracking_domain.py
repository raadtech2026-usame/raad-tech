"""Domain-only tests for `tracking`'s `VehiclePosition`/`GeofenceCrossing` entities and the
`GeofenceEvaluationService` domain service. Stdlib `unittest` — no `pytest`, matching
established precedent. Covers: value-object validation (`GeoPoint`/`SpeedKph`/
`HeadingDegrees`/`AlarmFlags` bounds), `VehiclePosition.record`'s event_time/received_at/
is_backfill handling, `GeofenceCrossing`'s stop_id-required invariant, and geofence
distance/containment/transition-detection correctness.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.tracking.domain.entities import GeofenceCrossing, VehiclePosition
from raad.modules.tracking.domain.services import GeofenceEvaluationService
from raad.modules.tracking.domain.value_objects import (
    AlarmFlags,
    DeviceId,
    GeofenceCrossingId,
    GeofenceEventType,
    GeofenceTransition,
    GeoPoint,
    HeadingDegrees,
    OrganizationId,
    SpeedKph,
    StopId,
    TripId,
    VehicleId,
    VehiclePositionId,
)

VALID_POSITION_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MC"
VALID_CROSSING_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


# --- Value objects ----------------------------------------------------------------------


class GeoPointTests(unittest.TestCase):
    def test_rejects_latitude_out_of_range(self) -> None:
        with self.assertRaises(DomainError):
            GeoPoint(latitude=91.0, longitude=0.0)

    def test_rejects_longitude_out_of_range(self) -> None:
        with self.assertRaises(DomainError):
            GeoPoint(latitude=0.0, longitude=181.0)

    def test_accepts_boundary_values(self) -> None:
        GeoPoint(latitude=90.0, longitude=180.0)
        GeoPoint(latitude=-90.0, longitude=-180.0)


class SpeedKphTests(unittest.TestCase):
    def test_rejects_negative_speed(self) -> None:
        with self.assertRaises(DomainError):
            SpeedKph(-1)

    def test_rejects_over_smallint_max(self) -> None:
        with self.assertRaises(DomainError):
            SpeedKph(32_768)

    def test_accepts_zero(self) -> None:
        SpeedKph(0)


class HeadingDegreesTests(unittest.TestCase):
    def test_rejects_360(self) -> None:
        with self.assertRaises(DomainError):
            HeadingDegrees(360)

    def test_rejects_negative(self) -> None:
        with self.assertRaises(DomainError):
            HeadingDegrees(-1)

    def test_accepts_zero_and_359(self) -> None:
        HeadingDegrees(0)
        HeadingDegrees(359)


class AlarmFlagsTests(unittest.TestCase):
    def test_rejects_negative(self) -> None:
        with self.assertRaises(DomainError):
            AlarmFlags(-1)

    def test_is_clear_true_for_zero(self) -> None:
        self.assertTrue(AlarmFlags(0).is_clear)

    def test_has_bit_detects_set_bit(self) -> None:
        flags = AlarmFlags(0b0101)
        self.assertTrue(flags.has_bit(0))
        self.assertFalse(flags.has_bit(1))
        self.assertTrue(flags.has_bit(2))


# --- VehiclePosition ----------------------------------------------------------------------


class VehiclePositionRecordTests(unittest.TestCase):
    def test_event_time_is_preserved_verbatim_not_replaced_with_now(self) -> None:
        """Regression: `.claude/rules/jt808.md` #3 - event_time is the device-reported time,
        never overwritten with ingest ('now') time."""
        device_reported_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        ingest_time = datetime(2026, 1, 1, 10, 5, 0, tzinfo=timezone.utc)  # 5 min later
        position = VehiclePosition.record(
            id=VehiclePositionId(VALID_POSITION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_POSITION_ULID),
            device_id=DeviceId(VALID_POSITION_ULID),
            position=GeoPoint(latitude=2.05, longitude=45.32),
            event_time=device_reported_time,
            clock=FixedClock(ingest_time),
        )
        self.assertEqual(position.event_time, device_reported_time)
        self.assertEqual(position.received_at, ingest_time)
        self.assertNotEqual(position.event_time, position.received_at)

    def test_live_position_is_not_backfill_by_default(self) -> None:
        position = VehiclePosition.record(
            id=VehiclePositionId(VALID_POSITION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_POSITION_ULID),
            device_id=DeviceId(VALID_POSITION_ULID),
            position=GeoPoint(latitude=2.05, longitude=45.32),
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertFalse(position.is_backfill)

    def test_backfill_position_is_flagged(self) -> None:
        """Regression: `.claude/rules/jt808.md` #3 - buffered/backfilled positions must be
        flagged, never presented as live."""
        position = VehiclePosition.record(
            id=VehiclePositionId(VALID_POSITION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_POSITION_ULID),
            device_id=DeviceId(VALID_POSITION_ULID),
            position=GeoPoint(latitude=2.05, longitude=45.32),
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            clock=FixedClock(datetime(2026, 1, 2, tzinfo=timezone.utc)),
            is_backfill=True,
        )
        self.assertTrue(position.is_backfill)

    def test_no_trip_id_defaults_to_none(self) -> None:
        position = VehiclePosition.record(
            id=VehiclePositionId(VALID_POSITION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_POSITION_ULID),
            device_id=DeviceId(VALID_POSITION_ULID),
            position=GeoPoint(latitude=2.05, longitude=45.32),
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertIsNone(position.trip_id)

    def test_position_emits_no_domain_event(self) -> None:
        """Regression: VehiclePosition is not an aggregate root and has no
        pull_domain_events - the fact was already announced by the JT808 plane."""
        position = VehiclePosition.record(
            id=VehiclePositionId(VALID_POSITION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            vehicle_id=VehicleId(VALID_POSITION_ULID),
            device_id=DeviceId(VALID_POSITION_ULID),
            position=GeoPoint(latitude=2.05, longitude=45.32),
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertFalse(hasattr(position, "pull_domain_events"))


# --- GeofenceCrossing -----------------------------------------------------------------------


class GeofenceCrossingInvariantTests(unittest.TestCase):
    def test_approaching_stop_requires_stop_id(self) -> None:
        with self.assertRaises(DomainError):
            GeofenceCrossing(
                id=GeofenceCrossingId(VALID_CROSSING_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                trip_id=TripId(VALID_ORG_ULID),
                stop_id=None,
                event_type=GeofenceEventType.APPROACHING_STOP,
                occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_entered_stop_requires_stop_id(self) -> None:
        with self.assertRaises(DomainError):
            GeofenceCrossing(
                id=GeofenceCrossingId(VALID_CROSSING_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                trip_id=TripId(VALID_ORG_ULID),
                stop_id=None,
                event_type=GeofenceEventType.ENTERED_STOP,
                occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_arrived_org_does_not_require_stop_id(self) -> None:
        crossing = GeofenceCrossing(
            id=GeofenceCrossingId(VALID_CROSSING_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            trip_id=TripId(VALID_ORG_ULID),
            stop_id=None,
            event_type=GeofenceEventType.ARRIVED_ORG,
            occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertIsNone(crossing.stop_id)

    def test_exited_does_not_require_stop_id(self) -> None:
        crossing = GeofenceCrossing(
            id=GeofenceCrossingId(VALID_CROSSING_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            trip_id=TripId(VALID_ORG_ULID),
            stop_id=None,
            event_type=GeofenceEventType.EXITED,
            occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertIsNone(crossing.stop_id)


class GeofenceCrossingFactoryTests(unittest.TestCase):
    def test_approaching_stop_records_matching_event(self) -> None:
        crossing = GeofenceCrossing.approaching_stop(
            id=GeofenceCrossingId(VALID_CROSSING_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            trip_id=TripId(VALID_ORG_ULID),
            stop_id=StopId(VALID_ORG_ULID),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(crossing.event_type, GeofenceEventType.APPROACHING_STOP)
        self.assertEqual(
            crossing.pull_domain_events()[0].event_type, "VehicleApproachingStop"
        )

    def test_entered_stop_records_matching_event(self) -> None:
        crossing = GeofenceCrossing.entered_stop(
            id=GeofenceCrossingId(VALID_CROSSING_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            trip_id=TripId(VALID_ORG_ULID),
            stop_id=StopId(VALID_ORG_ULID),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(
            crossing.pull_domain_events()[0].event_type, "VehicleEnteredStopGeofence"
        )

    def test_arrived_at_organization_records_matching_event(self) -> None:
        crossing = GeofenceCrossing.arrived_at_organization(
            id=GeofenceCrossingId(VALID_CROSSING_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            trip_id=TripId(VALID_ORG_ULID),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(
            crossing.pull_domain_events()[0].event_type, "VehicleArrivedAtOrganization"
        )

    def test_exited_records_matching_event(self) -> None:
        crossing = GeofenceCrossing.exited(
            id=GeofenceCrossingId(VALID_CROSSING_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            trip_id=TripId(VALID_ORG_ULID),
            stop_id=None,
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(
            crossing.pull_domain_events()[0].event_type, "VehicleExitedGeofence"
        )


# --- GeofenceEvaluationService ---------------------------------------------------------------


class GeofenceEvaluationServiceTests(unittest.TestCase):
    def test_distance_m_is_zero_for_identical_points(self) -> None:
        point = GeoPoint(latitude=2.0469, longitude=45.3182)
        self.assertAlmostEqual(GeofenceEvaluationService.distance_m(point, point), 0.0)

    def test_distance_m_known_approximate_distance(self) -> None:
        # Roughly 111km per degree of latitude at the equator - a 1-degree offset in latitude
        # should be close to 111,000 meters (haversine correctness sanity check).
        a = GeoPoint(latitude=0.0, longitude=0.0)
        b = GeoPoint(latitude=1.0, longitude=0.0)
        distance = GeofenceEvaluationService.distance_m(a, b)
        self.assertGreater(distance, 110_000)
        self.assertLess(distance, 112_000)

    def test_is_within_radius_true_when_inside(self) -> None:
        center = GeoPoint(latitude=2.0469, longitude=45.3182)
        position = GeoPoint(latitude=2.0469, longitude=45.3182)  # same point
        self.assertTrue(
            GeofenceEvaluationService.is_within_radius(
                position=position, center=center, radius_m=100
            )
        )

    def test_is_within_radius_false_when_outside(self) -> None:
        center = GeoPoint(latitude=0.0, longitude=0.0)
        far_position = GeoPoint(latitude=10.0, longitude=10.0)
        self.assertFalse(
            GeofenceEvaluationService.is_within_radius(
                position=far_position, center=center, radius_m=100
            )
        )

    def test_is_within_radius_rejects_negative_radius(self) -> None:
        center = GeoPoint(latitude=0.0, longitude=0.0)
        with self.assertRaises(ValueError):
            GeofenceEvaluationService.is_within_radius(
                position=center, center=center, radius_m=-1
            )

    def test_detect_transition_entered(self) -> None:
        result = GeofenceEvaluationService.detect_transition(
            was_inside=False, is_inside=True
        )
        self.assertEqual(result, GeofenceTransition.ENTERED)

    def test_detect_transition_exited(self) -> None:
        result = GeofenceEvaluationService.detect_transition(
            was_inside=True, is_inside=False
        )
        self.assertEqual(result, GeofenceTransition.EXITED)

    def test_detect_transition_none_when_unchanged_inside(self) -> None:
        result = GeofenceEvaluationService.detect_transition(
            was_inside=True, is_inside=True
        )
        self.assertEqual(result, GeofenceTransition.NONE)

    def test_detect_transition_none_when_unchanged_outside(self) -> None:
        result = GeofenceEvaluationService.detect_transition(
            was_inside=False, is_inside=False
        )
        self.assertEqual(result, GeofenceTransition.NONE)


if __name__ == "__main__":
    unittest.main()
