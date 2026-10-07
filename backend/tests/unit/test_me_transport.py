"""Unit tests for `MeApplicationService.get_my_transport` and its route (ADR-0060,
`GET /me/transport`). Stdlib `unittest`, plain fakes for the injected application services,
the same shape `test_me_application.py` uses.

What these protect: a parent reads only their own children's bus, route and stops; the route's
other stops never reach the response; and a dangling cross-module id is a `None`, not a 500.
"""

from __future__ import annotations

import inspect
import unittest
from dataclasses import asdict
from datetime import date, datetime, timezone
from types import SimpleNamespace

from raad.core.errors.exceptions import NotFoundError
from raad.core.tenancy.principal import Principal, Role
from raad.interfaces.http.deps import get_current_user
from raad.modules.iam.api.routers import get_my_transport, me_router
from raad.modules.iam.api.schemas import (
    MeChildTransportResponse,
    MeTransportAssignmentResponse,
    MeTransportStopResponse,
)
from raad.modules.iam.application.services import MeApplicationService
from raad.modules.transport_ops.application.queries import (
    RouteDTO,
    StopDTO,
    StudentAssignmentDTO,
    StudentForParentDTO,
    TripDTO,
)

NOW = datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc)

PARENT_A = Principal(user_id="user-a", role=Role.PARENT, org_id="org-1")
PARENT_B = Principal(user_id="user-b", role=Role.PARENT, org_id="org-1")


def _child(student_id: str, name: str) -> StudentForParentDTO:
    return StudentForParentDTO(
        student_id=student_id,
        full_name=name,
        status="active",
        relationship="mother",
        is_primary=True,
    )


def _stop(stop_id: str, seq: int) -> StopDTO:
    return StopDTO(
        id=stop_id,
        name=f"Stop {stop_id}",
        latitude=2.0 + seq / 100,
        longitude=45.0 + seq / 100,
        sequence_no=seq,
        geofence_radius_m=150,
    )


def _route(route_id: str, stop_ids: list[str]) -> RouteDTO:
    return RouteDTO(
        id=route_id,
        organization_id="org-1",
        name=f"Route {route_id}",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        stops=tuple(_stop(stop_id, i + 1) for i, stop_id in enumerate(stop_ids)),
    )


def _assignment(
    student_id: str,
    *,
    route_id: str = "route-1",
    pickup: str = "stop-1",
    dropoff: str = "stop-9",
    vehicle_id: str | None = "veh-1",
) -> StudentAssignmentDTO:
    return StudentAssignmentDTO(
        id=f"asg-{student_id}",
        organization_id="org-1",
        student_id=student_id,
        route_id=route_id,
        pickup_stop_id=pickup,
        dropoff_stop_id=dropoff,
        vehicle_id=vehicle_id,
        status="active",
        assigned_at=NOW,
        ended_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _trip(vehicle_id: str, route_id: str) -> TripDTO:
    return TripDTO(
        id=f"trip-{vehicle_id}",
        organization_id="org-1",
        vehicle_id=vehicle_id,
        driver_id="driver-1",
        route_id=route_id,
        trip_type="morning",
        status="in_progress",
        scheduled_date=date(2026, 10, 1),
        started_at=NOW,
        ended_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


class _Parents:
    def __init__(self, by_user_id: dict[str, str]) -> None:
        self._by_user_id = by_user_id

    async def get_parent_by_user_id(self, user_id: str, *, uow):
        parent_id = self._by_user_id.get(user_id)
        return SimpleNamespace(id=parent_id) if parent_id is not None else None


class _StudentParents:
    def __init__(self, by_parent_id: dict[str, list[StudentForParentDTO]]) -> None:
        self._by_parent_id = by_parent_id

    async def list_students_for_parent(self, query, *, uow):
        return self._by_parent_id.get(query.parent_id, [])


class _Assignments:
    def __init__(self, by_student_id: dict[str, StudentAssignmentDTO]) -> None:
        self._by_student_id = by_student_id
        self.asked: list[str] = []

    async def get_active_assignment_for_student(self, student_id: str, *, uow):
        self.asked.append(student_id)
        return self._by_student_id.get(student_id)


class _Routes:
    def __init__(self, by_id: dict[str, RouteDTO]) -> None:
        self._by_id = by_id
        self.asked: list[str] = []

    async def get_route_by_id(self, query, *, uow):
        self.asked.append(query.route_id)
        if query.route_id not in self._by_id:
            raise NotFoundError(f"Route {query.route_id} not found.")
        return self._by_id[query.route_id]


class _Trips:
    def __init__(self, active_by_vehicle: dict[str, TripDTO]) -> None:
        self._active_by_vehicle = active_by_vehicle
        self.asked: list[str] = []

    async def get_active_trip_for_vehicle(self, query, *, uow):
        self.asked.append(query.vehicle_id)
        return self._active_by_vehicle.get(query.vehicle_id)


class _Vehicles:
    def __init__(self, plates: dict[str, str]) -> None:
        self._plates = plates
        self.asked: list[str] = []

    async def get_vehicle_by_id(self, query, *, uow):
        self.asked.append(query.vehicle_id)
        if query.vehicle_id not in self._plates:
            raise NotFoundError(f"Vehicle {query.vehicle_id} not found.")
        return SimpleNamespace(
            id=query.vehicle_id, plate_no=self._plates[query.vehicle_id], label="Bus"
        )


def make_service(
    *,
    parents: dict[str, str] | None = None,
    children: dict[str, list[StudentForParentDTO]] | None = None,
    assignments: dict[str, StudentAssignmentDTO] | None = None,
    routes: dict[str, RouteDTO] | None = None,
    trips: dict[str, TripDTO] | None = None,
    vehicles: dict[str, str] | None = None,
) -> tuple[MeApplicationService, SimpleNamespace]:
    fakes = SimpleNamespace(
        assignments=_Assignments(assignments or {}),
        routes=_Routes(routes or {}),
        trips=_Trips(trips or {}),
        vehicles=_Vehicles(vehicles or {}),
    )
    service = MeApplicationService(
        parent_service=_Parents(parents or {}),  # type: ignore[arg-type]
        driver_service=None,  # type: ignore[arg-type]
        student_parent_service=_StudentParents(children or {}),  # type: ignore[arg-type]
        student_assignment_service=fakes.assignments,  # type: ignore[arg-type]
        route_service=fakes.routes,  # type: ignore[arg-type]
        trip_service=fakes.trips,  # type: ignore[arg-type]
        vehicle_service=fakes.vehicles,  # type: ignore[arg-type]
    )
    return service, fakes


async def _call(service: MeApplicationService, principal: Principal):
    return await service.get_my_transport(principal, uow="uow", fleet_device_uow="fleet-uow")


ROUTE_1 = _route("route-1", ["stop-1", "stop-2", "stop-3", "stop-9"])


class MyTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_children_on_one_bus(self) -> None:
        service, fakes = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina"), _child("s2", "Bilal")]},
            assignments={
                "s1": _assignment("s1", pickup="stop-1"),
                "s2": _assignment("s2", pickup="stop-2"),
            },
            routes={"route-1": ROUTE_1},
            vehicles={"veh-1": "AB-1234"},
        )

        result = await _call(service, PARENT_A)

        self.assertEqual([item.student_id for item in result], ["s1", "s2"])
        first, second = result
        self.assertEqual(first.full_name, "Amina")
        self.assertEqual(first.assignment.assignment_id, "asg-s1")
        self.assertEqual(first.assignment.route.name, "Route route-1")
        self.assertEqual(first.assignment.pickup_stop.id, "stop-1")
        self.assertEqual(first.assignment.dropoff_stop.id, "stop-9")
        self.assertEqual(first.assignment.vehicle.plate_no, "AB-1234")
        self.assertEqual(second.assignment.pickup_stop.id, "stop-2")
        # Siblings share the route and the bus: each is read once.
        self.assertEqual(fakes.routes.asked, ["route-1"])
        self.assertEqual(fakes.vehicles.asked, ["veh-1"])
        self.assertEqual(fakes.trips.asked, ["veh-1"])

    async def test_child_without_an_active_assignment(self) -> None:
        service, _ = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
        )

        (item,) = await _call(service, PARENT_A)

        self.assertEqual(item.student_id, "s1")
        self.assertIsNone(item.assignment)
        self.assertIsNone(item.current_trip)

    async def test_assignment_without_a_vehicle(self) -> None:
        service, fakes = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
            assignments={"s1": _assignment("s1", vehicle_id=None)},
            routes={"route-1": ROUTE_1},
        )

        (item,) = await _call(service, PARENT_A)

        self.assertIsNone(item.assignment.vehicle)
        self.assertIsNone(item.current_trip)
        self.assertEqual(item.assignment.route.id, "route-1")
        self.assertEqual(item.assignment.pickup_stop.id, "stop-1")
        self.assertEqual(fakes.trips.asked, [])

    async def test_in_progress_trip_on_the_childs_bus_and_route(self) -> None:
        service, _ = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
            assignments={"s1": _assignment("s1")},
            routes={"route-1": ROUTE_1},
            vehicles={"veh-1": "AB-1234"},
            trips={"veh-1": _trip("veh-1", "route-1")},
        )

        (item,) = await _call(service, PARENT_A)

        self.assertEqual(item.current_trip.id, "trip-veh-1")
        self.assertEqual(item.current_trip.status, "in_progress")
        self.assertEqual(item.current_trip.trip_type, "morning")
        self.assertEqual(item.current_trip.scheduled_date, date(2026, 10, 1))

    async def test_trip_on_the_same_bus_but_another_route_is_not_the_childs(self) -> None:
        service, _ = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
            assignments={"s1": _assignment("s1")},
            routes={"route-1": ROUTE_1},
            vehicles={"veh-1": "AB-1234"},
            trips={"veh-1": _trip("veh-1", "route-other")},
        )

        (item,) = await _call(service, PARENT_A)

        self.assertIsNone(item.current_trip)
        self.assertEqual(item.assignment.vehicle.id, "veh-1")

    async def test_no_in_progress_trip(self) -> None:
        service, _ = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
            assignments={"s1": _assignment("s1")},
            routes={"route-1": ROUTE_1},
            vehicles={"veh-1": "AB-1234"},
        )

        (item,) = await _call(service, PARENT_A)

        self.assertIsNone(item.current_trip)

    async def test_missing_route_yields_nulls_not_an_error(self) -> None:
        service, _ = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
            assignments={"s1": _assignment("s1")},
            vehicles={"veh-1": "AB-1234"},
        )

        (item,) = await _call(service, PARENT_A)

        self.assertIsNone(item.assignment.route)
        self.assertIsNone(item.assignment.pickup_stop)
        self.assertIsNone(item.assignment.dropoff_stop)
        self.assertEqual(item.assignment.vehicle.plate_no, "AB-1234")

    async def test_stop_no_longer_on_the_route_yields_null(self) -> None:
        service, _ = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
            assignments={"s1": _assignment("s1", pickup="stop-removed")},
            routes={"route-1": ROUTE_1},
            vehicles={"veh-1": "AB-1234"},
        )

        (item,) = await _call(service, PARENT_A)

        self.assertIsNone(item.assignment.pickup_stop)
        self.assertEqual(item.assignment.dropoff_stop.id, "stop-9")

    async def test_missing_vehicle_yields_null_not_an_error(self) -> None:
        service, _ = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
            assignments={"s1": _assignment("s1")},
            routes={"route-1": ROUTE_1},
        )

        (item,) = await _call(service, PARENT_A)

        self.assertIsNone(item.assignment.vehicle)
        self.assertEqual(item.assignment.route.id, "route-1")

    async def test_caller_without_a_parent_profile_is_not_found(self) -> None:
        service, fakes = make_service(parents={"user-a": "parent-a"})

        for principal in (
            Principal(user_id="user-driver", role=Role.DRIVER, org_id="org-1"),
            Principal(user_id="user-admin", role=Role.ORG_ADMIN, org_id="org-1"),
        ):
            with self.assertRaises(NotFoundError):
                await _call(service, principal)
        self.assertEqual(fakes.assignments.asked, [])


class MyTransportIsolationTests(unittest.IsolatedAsyncioTestCase):
    """Two families on different buses and routes. Neither sees anything of the other's."""

    def _service(self) -> MeApplicationService:
        service, _ = make_service(
            parents={"user-a": "parent-a", "user-b": "parent-b"},
            children={
                "parent-a": [_child("student-a", "Amina")],
                "parent-b": [_child("student-b", "Bashir")],
            },
            assignments={
                "student-a": _assignment(
                    "student-a", route_id="route-a", pickup="a-1", dropoff="a-2", vehicle_id="veh-a"
                ),
                "student-b": _assignment(
                    "student-b", route_id="route-b", pickup="b-1", dropoff="b-2", vehicle_id="veh-b"
                ),
            },
            routes={
                "route-a": _route("route-a", ["a-1", "a-2"]),
                "route-b": _route("route-b", ["b-1", "b-2"]),
            },
            vehicles={"veh-a": "PLATE-A", "veh-b": "PLATE-B"},
            trips={"veh-a": _trip("veh-a", "route-a"), "veh-b": _trip("veh-b", "route-b")},
        )
        return service

    async def test_parent_a_payload_contains_nothing_of_parent_b(self) -> None:
        result = await _call(self._service(), PARENT_A)

        payload = repr([asdict(item) for item in result])
        for leaked in ("student-b", "Bashir", "route-b", "b-1", "b-2", "veh-b", "PLATE-B"):
            self.assertNotIn(leaked, payload)
        for own in ("student-a", "route-a", "a-1", "a-2", "veh-a", "PLATE-A", "trip-veh-a"):
            self.assertIn(own, payload)

    async def test_parent_b_payload_contains_nothing_of_parent_a(self) -> None:
        result = await _call(self._service(), PARENT_B)

        payload = repr([asdict(item) for item in result])
        for leaked in ("student-a", "Amina", "route-a", "a-1", "a-2", "veh-a", "PLATE-A"):
            self.assertNotIn(leaked, payload)

    async def test_only_the_childs_own_two_stops_are_returned(self) -> None:
        """Two families share one route. Each sees their own stops, not the other's."""
        service, _ = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
            assignments={"s1": _assignment("s1", pickup="stop-2", dropoff="stop-9")},
            routes={"route-1": ROUTE_1},
            vehicles={"veh-1": "AB-1234"},
        )

        (item,) = await _call(service, PARENT_A)

        payload = repr(asdict(item))
        self.assertIn("stop-2", payload)
        self.assertIn("stop-9", payload)
        self.assertNotIn("stop-1", payload)
        self.assertNotIn("stop-3", payload)


class MyTransportContractTests(unittest.IsolatedAsyncioTestCase):
    def test_response_models_cannot_carry_other_stops_or_the_radius(self) -> None:
        self.assertEqual(
            set(MeTransportStopResponse.model_fields),
            {"id", "name", "latitude", "longitude"},
        )
        self.assertEqual(
            set(MeTransportAssignmentResponse.model_fields),
            {"assignment_id", "route", "pickup_stop", "dropoff_stop", "vehicle"},
        )
        self.assertEqual(
            set(MeChildTransportResponse.model_fields),
            {"student_id", "full_name", "status", "assignment", "current_trip"},
        )

    def test_route_takes_no_client_supplied_identity(self) -> None:
        parameters = inspect.signature(get_my_transport).parameters
        self.assertEqual(
            set(parameters), {"principal", "me_service", "uow", "fleet_device_uow"}
        )
        self.assertIs(parameters["principal"].default.dependency, get_current_user)

        (route,) = [r for r in me_router.routes if r.path.endswith("/transport")]
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route.param_convertors, {})
        self.assertEqual(route.dependant.query_params, [])
        self.assertEqual(route.dependant.path_params, [])
        self.assertIsNone(route.dependant.body_params or None)

    async def test_route_returns_the_documented_shape(self) -> None:
        service, _ = make_service(
            parents={"user-a": "parent-a"},
            children={"parent-a": [_child("s1", "Amina")]},
            assignments={"s1": _assignment("s1")},
            routes={"route-1": ROUTE_1},
            vehicles={"veh-1": "AB-1234"},
            trips={"veh-1": _trip("veh-1", "route-1")},
        )

        response = await get_my_transport(
            principal=PARENT_A, me_service=service, uow="uow", fleet_device_uow="fleet-uow"
        )

        self.assertEqual(
            [item.model_dump(mode="json") for item in response],
            [
                {
                    "student_id": "s1",
                    "full_name": "Amina",
                    "status": "active",
                    "assignment": {
                        "assignment_id": "asg-s1",
                        "route": {"id": "route-1", "name": "Route route-1"},
                        "pickup_stop": {
                            "id": "stop-1",
                            "name": "Stop stop-1",
                            "latitude": 2.01,
                            "longitude": 45.01,
                        },
                        "dropoff_stop": {
                            "id": "stop-9",
                            "name": "Stop stop-9",
                            "latitude": 2.04,
                            "longitude": 45.04,
                        },
                        "vehicle": {"id": "veh-1", "plate_no": "AB-1234", "label": "Bus"},
                    },
                    "current_trip": {
                        "id": "trip-veh-1",
                        "trip_type": "morning",
                        "status": "in_progress",
                        "scheduled_date": "2026-10-01",
                        "started_at": "2026-10-01T06:30:00Z",
                    },
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
