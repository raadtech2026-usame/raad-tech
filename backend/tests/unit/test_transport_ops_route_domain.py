"""Domain-only tests for `transport_ops`'s `Route` aggregate (+ `Stop` child entity) (Phase
11). Stdlib `unittest` — no `pytest` (not an approved dependency), matching
`test_transport_ops_driver_domain.py`'s established precedent exactly. Covers: value-object
validation (`RouteId`/`StopId`), construction invariants, state transitions (idempotent
no-ops), `update_details`, stop add/remove/move (including duplicate-sequence rejection and
coordinate/sequence validation), stop ordering, repository-interface shape, and domain-event
emission.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import ConflictError, DomainError
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain.entities import Route, Stop
from raad.modules.transport_ops.domain.repositories import RouteRepository
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    RouteId,
    RouteStatus,
    StopId,
)

VALID_ROUTE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MR"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_STOP_ULID_1 = "01J8Z3K9G6X8YV5T4N2R7QW3S1"
VALID_STOP_ULID_2 = "01J8Z3K9G6X8YV5T4N2R7QW3S2"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def make_route(**overrides) -> Route:
    defaults = dict(
        id=RouteId(VALID_ROUTE_ULID),
        organization_id=OrganizationId(VALID_ORG_ULID),
        name="Morning Route A",
        status=RouteStatus.ACTIVE,
    )
    defaults.update(overrides)
    return Route(**defaults)


class RouteIdValidationTests(unittest.TestCase):
    def test_valid_ulid_constructs(self) -> None:
        route_id = RouteId(VALID_ROUTE_ULID)
        self.assertEqual(str(route_id), VALID_ROUTE_ULID)

    def test_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            RouteId("TOOSHORT")

    def test_lowercase_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            RouteId(VALID_ROUTE_ULID.lower())

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            RouteId("")

    def test_equality_is_by_value(self) -> None:
        self.assertEqual(RouteId(VALID_ROUTE_ULID), RouteId(VALID_ROUTE_ULID))


class StopIdValidationTests(unittest.TestCase):
    def test_valid_ulid_constructs(self) -> None:
        stop_id = StopId(VALID_STOP_ULID_1)
        self.assertEqual(str(stop_id), VALID_STOP_ULID_1)

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            StopId("")


class RouteConstructionValidationTests(unittest.TestCase):
    def test_valid_route_constructs(self) -> None:
        route = make_route()
        self.assertEqual(route.name, "Morning Route A")
        self.assertEqual(route.status, RouteStatus.ACTIVE)
        self.assertEqual(route.stops, ())

    def test_empty_name_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_route(name="")

    def test_name_over_160_chars_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_route(name="A" * 161)

    def test_name_exactly_160_chars_is_valid(self) -> None:
        route = make_route(name="A" * 160)
        self.assertEqual(len(route.name), 160)

    def test_equality_is_by_id_not_by_field_values(self) -> None:
        a = make_route(name="Route One")
        b = make_route(name="Different Name")  # same id, different name
        self.assertEqual(a, b)

    def test_inequality_across_different_ids(self) -> None:
        other_id = "01J8Z3K9G6X8YV5T4N2R7QW3MX"
        a = make_route()
        b = make_route(id=RouteId(other_id))
        self.assertNotEqual(a, b)

    def test_hash_matches_id_hash(self) -> None:
        route = make_route()
        self.assertEqual(hash(route), hash(route.id))


class RouteCreateTests(unittest.TestCase):
    def test_create_starts_active(self) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        route = Route.create(
            id=RouteId(VALID_ROUTE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            name="Morning Route A",
            clock=clock,
        )
        self.assertEqual(route.status, RouteStatus.ACTIVE)

    def test_create_records_route_created_event(self) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        route = Route.create(
            id=RouteId(VALID_ROUTE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            name="Morning Route A",
            clock=clock,
            actor_id="actor-1",
        )
        events = route.pull_domain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "RouteCreated")
        self.assertEqual(event.aggregate_type, "Route")
        self.assertEqual(event.aggregate_id, VALID_ROUTE_ULID)
        self.assertEqual(event.org_id, VALID_ORG_ULID)
        self.assertEqual(event.occurred_at, clock.now())
        self.assertEqual(
            event.payload, {"name": "Morning Route A", "actor_id": "actor-1"}
        )

    def test_create_with_invalid_name_raises_before_recording_event(self) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        with self.assertRaises(DomainError):
            Route.create(
                id=RouteId(VALID_ROUTE_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                name="",
                clock=clock,
            )


class RouteStatusTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))

    def test_disable_changes_status_and_records_event(self) -> None:
        route = make_route(status=RouteStatus.ACTIVE)
        route.disable(clock=self.clock, actor_id="admin-1")
        self.assertEqual(route.status, RouteStatus.INACTIVE)
        events = route.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "RouteDisabled")
        self.assertEqual(events[0].payload, {"actor_id": "admin-1"})

    def test_activate_changes_status_and_records_event(self) -> None:
        route = make_route(status=RouteStatus.INACTIVE)
        route.activate(clock=self.clock)
        self.assertEqual(route.status, RouteStatus.ACTIVE)
        events = route.pull_domain_events()
        self.assertEqual(events[0].event_type, "RouteActivated")

    def test_disable_when_already_inactive_is_idempotent_no_op(self) -> None:
        route = make_route(status=RouteStatus.INACTIVE)
        route.disable(clock=self.clock)
        self.assertEqual(route.pull_domain_events(), [])

    def test_activate_when_already_active_is_idempotent_no_op(self) -> None:
        route = make_route(status=RouteStatus.ACTIVE)
        route.activate(clock=self.clock)
        self.assertEqual(route.pull_domain_events(), [])


class RouteUpdateDetailsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))

    def test_update_details_changes_name_and_records_event(self) -> None:
        route = make_route(name="Old Name")
        route.update_details(name="New Name", clock=self.clock, actor_id="admin-1")
        self.assertEqual(route.name, "New Name")
        events = route.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "RouteDetailsUpdated")
        self.assertEqual(events[0].payload, {"name": "New Name", "actor_id": "admin-1"})

    def test_update_details_with_identical_value_is_idempotent_no_op(self) -> None:
        route = make_route(name="Same Name")
        route.update_details(name="Same Name", clock=self.clock)
        self.assertEqual(route.pull_domain_events(), [])

    def test_update_details_rejects_empty_name(self) -> None:
        route = make_route()
        with self.assertRaises(DomainError):
            route.update_details(name="", clock=self.clock)


class RouteAddStopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))

    def test_add_stop_appends_and_returns_stop(self) -> None:
        route = make_route()
        stop = route.add_stop(
            id=StopId(VALID_STOP_ULID_1),
            name="First Stop",
            latitude=2.5,
            longitude=45.3,
            sequence_no=1,
            clock=self.clock,
        )
        self.assertIsInstance(stop, Stop)
        self.assertEqual(len(route.stops), 1)
        self.assertIs(route.stops[0], stop)

    def test_add_stop_records_route_stop_added_event(self) -> None:
        route = make_route()
        route.add_stop(
            id=StopId(VALID_STOP_ULID_1),
            name="First Stop",
            latitude=2.5,
            longitude=45.3,
            sequence_no=1,
            geofence_radius_m=50,
            clock=self.clock,
            actor_id="admin-1",
        )
        events = route.pull_domain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "RouteStopAdded")
        self.assertEqual(event.aggregate_type, "Route")
        self.assertEqual(event.aggregate_id, str(route.id))
        self.assertEqual(
            event.payload,
            {
                "stop_id": VALID_STOP_ULID_1,
                "name": "First Stop",
                "latitude": 2.5,
                "longitude": 45.3,
                "sequence_no": 1,
                "geofence_radius_m": 50,
                "actor_id": "admin-1",
            },
        )

    def test_add_stop_with_duplicate_sequence_no_raises_conflict_error(self) -> None:
        route = make_route()
        route.add_stop(
            id=StopId(VALID_STOP_ULID_1),
            name="First Stop",
            latitude=2.5,
            longitude=45.3,
            sequence_no=1,
            clock=self.clock,
        )
        with self.assertRaises(ConflictError):
            route.add_stop(
                id=StopId(VALID_STOP_ULID_2),
                name="Second Stop",
                latitude=2.6,
                longitude=45.4,
                sequence_no=1,
                clock=self.clock,
            )

    def test_add_stop_with_zero_sequence_no_raises_domain_error(self) -> None:
        route = make_route()
        with self.assertRaises(DomainError):
            route.add_stop(
                id=StopId(VALID_STOP_ULID_1),
                name="First Stop",
                latitude=2.5,
                longitude=45.3,
                sequence_no=0,
                clock=self.clock,
            )

    def test_add_stop_with_negative_sequence_no_raises_domain_error(self) -> None:
        route = make_route()
        with self.assertRaises(DomainError):
            route.add_stop(
                id=StopId(VALID_STOP_ULID_1),
                name="First Stop",
                latitude=2.5,
                longitude=45.3,
                sequence_no=-1,
                clock=self.clock,
            )

    def test_add_stop_with_latitude_over_90_raises_domain_error(self) -> None:
        route = make_route()
        with self.assertRaises(DomainError):
            route.add_stop(
                id=StopId(VALID_STOP_ULID_1),
                name="First Stop",
                latitude=90.1,
                longitude=45.3,
                sequence_no=1,
                clock=self.clock,
            )

    def test_add_stop_with_latitude_under_negative_90_raises_domain_error(
        self,
    ) -> None:
        route = make_route()
        with self.assertRaises(DomainError):
            route.add_stop(
                id=StopId(VALID_STOP_ULID_1),
                name="First Stop",
                latitude=-90.1,
                longitude=45.3,
                sequence_no=1,
                clock=self.clock,
            )

    def test_add_stop_with_longitude_over_180_raises_domain_error(self) -> None:
        route = make_route()
        with self.assertRaises(DomainError):
            route.add_stop(
                id=StopId(VALID_STOP_ULID_1),
                name="First Stop",
                latitude=2.5,
                longitude=180.1,
                sequence_no=1,
                clock=self.clock,
            )

    def test_add_stop_boundary_coordinates_are_valid(self) -> None:
        route = make_route()
        stop = route.add_stop(
            id=StopId(VALID_STOP_ULID_1),
            name="Boundary Stop",
            latitude=90.0,
            longitude=-180.0,
            sequence_no=1,
            clock=self.clock,
        )
        self.assertEqual(stop.latitude, 90.0)
        self.assertEqual(stop.longitude, -180.0)

    def test_add_stop_with_empty_name_raises_domain_error(self) -> None:
        route = make_route()
        with self.assertRaises(DomainError):
            route.add_stop(
                id=StopId(VALID_STOP_ULID_1),
                name="",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                clock=self.clock,
            )

    def test_stops_are_always_returned_ordered_by_sequence_no(self) -> None:
        route = make_route()
        route.add_stop(
            id=StopId(VALID_STOP_ULID_2),
            name="Second Stop",
            latitude=2.6,
            longitude=45.4,
            sequence_no=2,
            clock=self.clock,
        )
        route.add_stop(
            id=StopId(VALID_STOP_ULID_1),
            name="First Stop",
            latitude=2.5,
            longitude=45.3,
            sequence_no=1,
            clock=self.clock,
        )
        # Added out of order (seq 2 then seq 1) - stops property must still return in
        # ascending sequence_no order.
        self.assertEqual([s.sequence_no for s in route.stops], [1, 2])
        self.assertEqual([s.name for s in route.stops], ["First Stop", "Second Stop"])


class RouteRemoveStopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        self.route = make_route()
        self.stop = self.route.add_stop(
            id=StopId(VALID_STOP_ULID_1),
            name="First Stop",
            latitude=2.5,
            longitude=45.3,
            sequence_no=1,
            clock=self.clock,
        )
        self.route.pull_domain_events()  # isolate remove's own event from add's

    def test_remove_stop_removes_from_collection(self) -> None:
        self.route.remove_stop(self.stop.id, clock=self.clock)
        self.assertEqual(self.route.stops, ())

    def test_remove_stop_records_route_stop_removed_event(self) -> None:
        self.route.remove_stop(self.stop.id, clock=self.clock, actor_id="admin-1")
        events = self.route.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "RouteStopRemoved")
        self.assertEqual(
            events[0].payload,
            {"stop_id": str(self.stop.id), "actor_id": "admin-1"},
        )

    def test_remove_missing_stop_raises_domain_error(self) -> None:
        other_id = StopId(VALID_STOP_ULID_2)
        with self.assertRaises(DomainError):
            self.route.remove_stop(other_id, clock=self.clock)


class RouteMoveStopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        self.route = make_route()
        self.stop1 = self.route.add_stop(
            id=StopId(VALID_STOP_ULID_1),
            name="First Stop",
            latitude=2.5,
            longitude=45.3,
            sequence_no=1,
            clock=self.clock,
        )
        self.stop2 = self.route.add_stop(
            id=StopId(VALID_STOP_ULID_2),
            name="Second Stop",
            latitude=2.6,
            longitude=45.4,
            sequence_no=2,
            clock=self.clock,
        )
        self.route.pull_domain_events()  # isolate move's own event from add's

    def test_move_stop_changes_sequence_no(self) -> None:
        self.route.move_stop(self.stop1.id, new_sequence_no=5, clock=self.clock)
        self.assertEqual(self.stop1.sequence_no, 5)

    def test_move_stop_records_route_stop_reordered_event(self) -> None:
        self.route.move_stop(
            self.stop1.id, new_sequence_no=5, clock=self.clock, actor_id="admin-1"
        )
        events = self.route.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "RouteStopReordered")
        self.assertEqual(
            events[0].payload,
            {
                "stop_id": str(self.stop1.id),
                "new_sequence_no": 5,
                "actor_id": "admin-1",
            },
        )

    def test_move_stop_to_same_sequence_is_idempotent_no_op(self) -> None:
        self.route.move_stop(self.stop1.id, new_sequence_no=1, clock=self.clock)
        self.assertEqual(self.route.pull_domain_events(), [])

    def test_move_stop_to_occupied_sequence_raises_conflict_error(self) -> None:
        with self.assertRaises(ConflictError):
            self.route.move_stop(self.stop1.id, new_sequence_no=2, clock=self.clock)

    def test_move_stop_to_invalid_sequence_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            self.route.move_stop(self.stop1.id, new_sequence_no=0, clock=self.clock)

    def test_move_missing_stop_raises_domain_error(self) -> None:
        missing_id = StopId("01J8Z3K9G6X8YV5T4N2R7QW3ZZ")
        with self.assertRaises(DomainError):
            self.route.move_stop(missing_id, new_sequence_no=3, clock=self.clock)


class DomainEventBufferingTests(unittest.TestCase):
    def test_pull_domain_events_drains_the_buffer(self) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        route = Route.create(
            id=RouteId(VALID_ROUTE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            name="Morning Route A",
            clock=clock,
        )
        first_pull = route.pull_domain_events()
        second_pull = route.pull_domain_events()
        self.assertEqual(len(first_pull), 1)
        self.assertEqual(second_pull, [])

    def test_multiple_mutations_buffer_multiple_events_in_order(self) -> None:
        clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
        route = make_route(status=RouteStatus.ACTIVE)
        route.disable(clock=clock)
        route.activate(clock=clock)
        events = route.pull_domain_events()
        self.assertEqual(
            [e.event_type for e in events], ["RouteDisabled", "RouteActivated"]
        )


class RouteRepositoryInterfaceTests(unittest.TestCase):
    def test_cannot_instantiate_abstract_repository_directly(self) -> None:
        with self.assertRaises(TypeError):
            RouteRepository()  # abstract - no concrete get/get_by_name/add/list_all

    def test_concrete_implementation_satisfying_the_interface_can_be_instantiated(
        self,
    ) -> None:
        class InMemoryRouteRepository(RouteRepository):
            def __init__(self) -> None:
                self._routes: dict[str, Route] = {}

            async def get(self, route_id: RouteId) -> Route | None:
                return self._routes.get(str(route_id))

            async def get_by_name(self, name: str) -> Route | None:
                return next((r for r in self._routes.values() if r.name == name), None)

            def add(self, route: Route) -> None:
                self._routes[str(route.id)] = route

            async def list_all(self) -> list[Route]:
                return list(self._routes.values())

        repo = InMemoryRouteRepository()
        route = make_route()
        repo.add(route)
        self.assertIs(repo._routes[str(route.id)], route)

    def test_incomplete_implementation_missing_add_cannot_be_instantiated(self) -> None:
        class IncompleteRepository(RouteRepository):
            async def get(self, route_id: RouteId) -> Route | None:
                return None

            async def get_by_name(self, name: str) -> Route | None:
                return None

        with self.assertRaises(TypeError):
            IncompleteRepository()


if __name__ == "__main__":
    unittest.main()
