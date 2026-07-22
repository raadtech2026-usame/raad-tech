"""Unit tests for `modules.tracking.api.ws` — `/ws/tracking`'s connection lifecycle, subscribe
authorization, and broker-event fan-out. Stdlib `unittest` — no `pytest` (not an approved
dependency). Fakes are bound directly into a real `core.di.container.Container`, mirroring
`test_policy_guards.py`'s own established convention (this file needs the identical CR-1/D4
policy chain `resolve_tracking_decision`/`resolve_vehicle_tracking_context` already exercise
end-to-end there — those functions' own correctness is covered *there*; this file covers the
WebSocket-specific glue around them: subscribe/unsubscribe, connection registration, per-send
re-authorization, and the two broker event types this channel reacts to).
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from raad.core.di.container import Container
from raad.core.errors.exceptions import NotFoundError
from raad.core.events.base import DomainEvent
from raad.core.security.tokens import JwtTokenService, TokenService
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.resolver import ScopeResolver
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.interfaces.http.realtime import ConnectionManager, WsCloseCode
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import VehicleApplicationService
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.services import OrganizationApplicationService
from raad.modules.tracking.api.ws import (
    build_tracking_fanout_handler,
    handle_subscribe,
    run_tracking_websocket,
)
from raad.modules.tracking.application.services import TrackingApplicationService
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.services import (
    ParentApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
    TripApplicationService,
)

ORG_ID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
PARENT = Principal(user_id="user-1", role=Role.PARENT, org_id=ORG_ID)
ORG_ADMIN = Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=ORG_ID)


@dataclass(frozen=True)
class _VehicleDTO:
    organization_id: str


@dataclass(frozen=True)
class _PositionDTO:
    trip_id: str | None


@dataclass(frozen=True)
class _TripStatusDTO:
    status: str


@dataclass(frozen=True)
class _ParentDTO:
    id: str


@dataclass(frozen=True)
class _StudentLinkDTO:
    student_id: str


@dataclass(frozen=True)
class _AssignmentDTO:
    status: str
    vehicle_id: str | None = None


class FakeVehicleService:
    def __init__(self, vehicles_by_id: dict[str, _VehicleDTO]) -> None:
        self._by_id = vehicles_by_id

    async def get_vehicle_by_id(self, query, *, uow):
        vehicle = self._by_id.get(query.vehicle_id)
        if vehicle is None:
            raise NotFoundError(f"Vehicle {query.vehicle_id} not found.")
        return vehicle


class FakeTrackingService:
    def __init__(self, position_by_vehicle: dict[str, _PositionDTO | None] | None = None) -> None:
        self._by_vehicle = position_by_vehicle or {}

    async def get_current_vehicle_position(self, query):
        return self._by_vehicle.get(query.vehicle_id)


class FakeTripService:
    def __init__(self, trip_by_id: dict[str, _TripStatusDTO] | None = None) -> None:
        self._by_id = trip_by_id or {}

    async def get_trip_by_id(self, query, *, uow):
        return self._by_id[query.trip_id]


class FakeParentService:
    def __init__(self, parent_by_user_id: dict[str, _ParentDTO]) -> None:
        self._by_user_id = parent_by_user_id

    async def get_parent_by_user_id(self, user_id, *, uow):
        return self._by_user_id.get(user_id)


class FakeStudentParentService:
    def __init__(self, children_by_parent: dict[str, list[_StudentLinkDTO]]) -> None:
        self._children_by_parent = children_by_parent

    async def list_students_for_parent(self, query, *, uow):
        return list(self._children_by_parent.get(query.parent_id, []))


class FakeStudentAssignmentService:
    def __init__(self, assignment_by_student: dict[str, _AssignmentDTO | None]) -> None:
        self._by_student = assignment_by_student

    async def get_active_assignment_for_student(self, student_id, *, uow):
        return self._by_student.get(student_id)


class FakeOrganizationService:
    def __init__(self, billing_model: str) -> None:
        self._billing_model = billing_model

    async def get_organization_by_id(self, query, *, uow):
        return type("OrgDTO", (), {"billing_model": self._billing_model})()


class FakeBillingService:
    async def get_active_subscription_for_subscriber(self, subscriber_type, subscriber_id, *, uow):
        return None


class FakeScopeResolver(ScopeResolver):
    def __init__(self, scope: TenantRegionScope) -> None:
        self._scope = scope

    async def effective_org_scope(self, principal: Principal) -> TenantRegionScope:
        return self._scope


def make_container(
    *,
    vehicles: dict[str, _VehicleDTO] | None = None,
    positions: dict[str, _PositionDTO | None] | None = None,
    trips: dict[str, _TripStatusDTO] | None = None,
    parent_id: str = "parent-1",
    children: list[str] | None = None,
    assignments: dict[str, _AssignmentDTO | None] | None = None,
    billing_model: str = "organization_pays",
    scope: TenantRegionScope = TenantRegionScope(organization_ids=frozenset({ORG_ID})),
) -> Container:
    container = Container()
    container.bind_singleton(VehicleApplicationService, FakeVehicleService(vehicles or {}))
    container.bind_singleton(TrackingApplicationService, FakeTrackingService(positions))
    container.bind_singleton(TripApplicationService, FakeTripService(trips))
    container.bind_singleton(
        ParentApplicationService, FakeParentService({"user-1": _ParentDTO(id=parent_id)})
    )
    container.bind_singleton(
        StudentParentApplicationService,
        FakeStudentParentService(
            {parent_id: [_StudentLinkDTO(student_id=s) for s in (children or [])]}
        ),
    )
    container.bind_singleton(
        StudentAssignmentApplicationService, FakeStudentAssignmentService(assignments or {})
    )
    container.bind_singleton(OrganizationApplicationService, FakeOrganizationService(billing_model))
    container.bind_singleton(BillingApplicationService, FakeBillingService())
    container.bind_singleton(ScopeResolver, FakeScopeResolver(scope))
    for uow_type in (
        TransportOpsUnitOfWork,
        OrganizationUnitOfWork,
        BillingUnitOfWork,
        FleetDeviceUnitOfWork,
    ):
        container.bind_singleton(uow_type, object())
    return container


class FakeWebSocket:
    def __init__(self, *, messages: list[object] | None = None) -> None:
        self._messages = list(messages or [])
        self.sent: list[object] = []
        self.closed_with: int | None = None
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: object) -> None:
        self.sent.append(data)

    async def receive_json(self) -> object:
        if not self._messages:
            raise RuntimeError("no more fake messages queued")
        return self._messages.pop(0)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


def make_token_service() -> JwtTokenService:
    return JwtTokenService(
        secret_key="test-secret",
        algorithm="HS256",
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=1_209_600,
        clock=SystemClock(),
    )


def make_event(event_type: str, payload: dict[str, object]) -> DomainEvent:
    return DomainEvent(
        event_id="evt-1",
        event_type=event_type,
        version=1,
        occurred_at=SystemClock().now(),
        org_id=ORG_ID,
        correlation_id=None,
        payload=payload,
        aggregate_type="Vehicle",
        aggregate_id=payload.get("vehicle_id", "veh-1"),
    )


class HandleSubscribeTests(unittest.IsolatedAsyncioTestCase):
    async def test_org_admin_subscribe_registers_the_connection(self) -> None:
        container = make_container(vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)})
        connections = ConnectionManager()
        websocket = FakeWebSocket()

        result = await handle_subscribe(
            {"type": "subscribe", "channel": "vehicle", "vehicle_id": "veh-1"},
            websocket=websocket,
            principal=ORG_ADMIN,
            container=container,
            connections=connections,
            current_vehicle_id=None,
        )

        self.assertEqual(result, "veh-1")
        self.assertEqual(len(await connections.subscribers_for("veh-1")), 1)
        self.assertIsNone(websocket.closed_with)

    async def test_parent_subscribe_to_owned_vehicle_with_active_trip_is_granted(self) -> None:
        container = make_container(
            vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)},
            positions={"veh-1": _PositionDTO(trip_id="trip-1")},
            trips={"trip-1": _TripStatusDTO(status="in_progress")},
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active", vehicle_id="veh-1")},
            billing_model="parent_pays",  # no subscription bound - only D4 override saves this
        )
        connections = ConnectionManager()
        websocket = FakeWebSocket()

        result = await handle_subscribe(
            {"type": "subscribe", "channel": "vehicle", "vehicle_id": "veh-1"},
            websocket=websocket,
            principal=PARENT,
            container=container,
            connections=connections,
            current_vehicle_id=None,
        )

        self.assertEqual(result, "veh-1")

    async def test_parent_subscribe_to_unowned_vehicle_is_denied_and_closes_forbidden(self) -> None:
        container = make_container(
            vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)}, children=[]
        )
        connections = ConnectionManager()
        websocket = FakeWebSocket()

        result = await handle_subscribe(
            {"type": "subscribe", "channel": "vehicle", "vehicle_id": "veh-1"},
            websocket=websocket,
            principal=PARENT,
            container=container,
            connections=connections,
            current_vehicle_id=None,
        )

        self.assertIsNone(result)
        self.assertEqual(websocket.closed_with, WsCloseCode.FORBIDDEN)
        self.assertEqual(await connections.subscribers_for("veh-1"), [])

    async def test_subscribe_to_nonexistent_vehicle_closes_forbidden_not_a_leak(self) -> None:
        """404-over-403 posture applied to a close code: "vehicle doesn't exist" and "exists
        but denied" must be indistinguishable from the client's perspective."""
        container = make_container(vehicles={})
        websocket = FakeWebSocket()

        result = await handle_subscribe(
            {"type": "subscribe", "channel": "vehicle", "vehicle_id": "veh-ghost"},
            websocket=websocket,
            principal=ORG_ADMIN,
            container=container,
            connections=ConnectionManager(),
            current_vehicle_id=None,
        )

        self.assertIsNone(result)
        self.assertEqual(websocket.closed_with, WsCloseCode.FORBIDDEN)

    async def test_malformed_vehicle_id_closes_bad_request_instead_of_crashing(self) -> None:
        """Regression test for a real bug an ASGI-level smoke test caught during review: a
        `vehicle_id` that isn't a 26-character ULID fails `VehicleId.__post_init__`'s own
        validation with a `DomainError` deep inside `resolve_vehicle_tracking_context` — this
        must close the socket cleanly with `BAD_REQUEST`, never let the `DomainError` propagate
        up to FastAPI's HTTP-only global exception handler (which cannot safely respond on an
        already-accepted WebSocket at all — see `handle_subscribe`'s own docstring)."""

        class RaisingVehicleService:
            async def get_vehicle_by_id(self, query, *, uow):
                from raad.core.errors.exceptions import DomainError

                raise DomainError(
                    f"VehicleId must be a 26-character ULID: {query.vehicle_id!r}"
                )

        container = make_container()
        container.bind_singleton(VehicleApplicationService, RaisingVehicleService())
        websocket = FakeWebSocket()

        result = await handle_subscribe(
            {"type": "subscribe", "channel": "vehicle", "vehicle_id": "not-a-valid-ulid"},
            websocket=websocket,
            principal=ORG_ADMIN,
            container=container,
            connections=ConnectionManager(),
            current_vehicle_id=None,
        )

        self.assertIsNone(result)
        self.assertEqual(websocket.closed_with, WsCloseCode.BAD_REQUEST)

    async def test_missing_vehicle_id_closes_bad_request(self) -> None:
        websocket = FakeWebSocket()
        result = await handle_subscribe(
            {"type": "subscribe", "channel": "vehicle"},
            websocket=websocket,
            principal=ORG_ADMIN,
            container=make_container(),
            connections=ConnectionManager(),
            current_vehicle_id=None,
        )
        self.assertIsNone(result)
        self.assertEqual(websocket.closed_with, WsCloseCode.BAD_REQUEST)

    async def test_wrong_channel_closes_bad_request(self) -> None:
        websocket = FakeWebSocket()
        result = await handle_subscribe(
            {"type": "subscribe", "channel": "fleet", "vehicle_id": "veh-1"},
            websocket=websocket,
            principal=ORG_ADMIN,
            container=make_container(),
            connections=ConnectionManager(),
            current_vehicle_id=None,
        )
        self.assertIsNone(result)
        self.assertEqual(websocket.closed_with, WsCloseCode.BAD_REQUEST)

    async def test_resubscribing_to_a_new_vehicle_unregisters_the_old_one(self) -> None:
        container = make_container(
            vehicles={
                "veh-1": _VehicleDTO(organization_id=ORG_ID),
                "veh-2": _VehicleDTO(organization_id=ORG_ID),
            }
        )
        connections = ConnectionManager()
        websocket = FakeWebSocket()
        await connections.register("veh-1", websocket, ORG_ADMIN)

        result = await handle_subscribe(
            {"type": "subscribe", "channel": "vehicle", "vehicle_id": "veh-2"},
            websocket=websocket,
            principal=ORG_ADMIN,
            container=container,
            connections=connections,
            current_vehicle_id="veh-1",
        )

        self.assertEqual(result, "veh-2")
        self.assertEqual(await connections.subscribers_for("veh-1"), [])
        self.assertEqual(len(await connections.subscribers_for("veh-2")), 1)


class TrackingFanoutHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_position_event_forwards_frame_to_authorized_subscriber(self) -> None:
        container = make_container(vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)})
        connections = ConnectionManager()
        websocket = FakeWebSocket()
        await connections.register("veh-1", websocket, ORG_ADMIN)
        handler = build_tracking_fanout_handler(connections=connections, container=container)

        event = make_event(
            "DevicePositionReported",
            {
                "vehicle_id": "veh-1",
                "trip_id": "trip-1",
                "lat": 2.0469,
                "lng": 45.3182,
                "speed_kph": 34,
                "heading_deg": 120,
                "event_time": "2026-07-22T08:00:00Z",
            },
        )
        await handler(event)

        self.assertEqual(len(websocket.sent), 1)
        frame = websocket.sent[0]
        self.assertEqual(frame["type"], "position")
        self.assertEqual(frame["vehicle_id"], "veh-1")
        self.assertEqual(frame["lat"], 2.0469)
        self.assertEqual(frame["speed_kph"], 34)

    async def test_position_event_with_no_subscribers_is_a_no_op(self) -> None:
        container = make_container(vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)})
        handler = build_tracking_fanout_handler(
            connections=ConnectionManager(), container=container
        )
        await handler(make_event("DevicePositionReported", {"vehicle_id": "veh-1"}))  # no raise

    async def test_position_event_closes_now_unauthorized_parent_subscriber(self) -> None:
        """The re-check-on-every-send mechanism (`tracking.api.ws`'s own module docstring) —
        a Parent whose assignment has since been removed must be dropped and closed on the
        very next position push, without any event-payload-to-vehicle_id translation."""
        container = make_container(
            vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)},
            children=["s1"],
            assignments={},  # assignment now gone - simulates a since-revoked assignment
        )
        connections = ConnectionManager()
        websocket = FakeWebSocket()
        await connections.register("veh-1", websocket, PARENT)
        handler = build_tracking_fanout_handler(connections=connections, container=container)

        await handler(make_event("DevicePositionReported", {"vehicle_id": "veh-1", "lat": 1.0}))

        self.assertEqual(websocket.sent, [])
        self.assertEqual(websocket.closed_with, WsCloseCode.FORBIDDEN)
        self.assertEqual(await connections.subscribers_for("veh-1"), [])

    async def test_trip_ended_event_sends_subscription_closed_then_closes(self) -> None:
        connections = ConnectionManager()
        websocket = FakeWebSocket()
        await connections.register("veh-1", websocket, ORG_ADMIN)
        handler = build_tracking_fanout_handler(
            connections=connections, container=make_container()
        )

        await handler(make_event("TripEnded", {"vehicle_id": "veh-1"}))

        self.assertEqual(
            websocket.sent,
            [{"type": "subscription_closed", "vehicle_id": "veh-1", "reason": "trip_ended"}],
        )
        self.assertEqual(websocket.closed_with, 1000)
        self.assertEqual(await connections.subscribers_for("veh-1"), [])

    async def test_unrelated_event_type_is_ignored(self) -> None:
        connections = ConnectionManager()
        websocket = FakeWebSocket()
        await connections.register("veh-1", websocket, ORG_ADMIN)
        handler = build_tracking_fanout_handler(
            connections=connections, container=make_container()
        )

        await handler(make_event("StudentEnrolled", {"vehicle_id": "veh-1"}))

        self.assertEqual(websocket.sent, [])
        self.assertIsNone(websocket.closed_with)


class RunTrackingWebsocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_happy_path_authenticates_subscribes_and_cleans_up_on_disconnect(
        self,
    ) -> None:
        from fastapi import WebSocketDisconnect

        class DisconnectingWebSocket(FakeWebSocket):
            async def receive_json(self):
                if not self._messages:
                    raise WebSocketDisconnect(code=1000)
                return self._messages.pop(0)

        token_service = make_token_service()
        pair = token_service.issue_token_pair(
            subject="admin-1", role=Role.ORG_ADMIN, org_id=ORG_ID
        )
        container = make_container(vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)})
        container.bind_singleton(TokenService, token_service)
        connections = ConnectionManager()
        websocket = DisconnectingWebSocket(
            messages=[
                {"type": "auth", "token": pair.access_token},
                {"type": "subscribe", "channel": "vehicle", "vehicle_id": "veh-1"},
            ]
        )

        await run_tracking_websocket(
            websocket,
            container=container,
            connections=connections,
            auth_frame_timeout_seconds=5.0,
        )

        self.assertTrue(websocket.accepted)
        self.assertEqual(await connections.subscribers_for("veh-1"), [])  # cleaned up

    async def test_no_token_service_bound_closes_unauthenticated(self) -> None:
        container = make_container()
        websocket = FakeWebSocket()

        await run_tracking_websocket(
            websocket,
            container=container,
            connections=ConnectionManager(),
            auth_frame_timeout_seconds=5.0,
        )

        self.assertEqual(websocket.closed_with, WsCloseCode.UNAUTHENTICATED)

    async def test_invalid_auth_frame_closes_unauthenticated(self) -> None:
        container = make_container()
        container.bind_singleton(TokenService, make_token_service())
        websocket = FakeWebSocket(messages=[{"type": "auth", "token": "garbage"}])

        await run_tracking_websocket(
            websocket,
            container=container,
            connections=ConnectionManager(),
            auth_frame_timeout_seconds=5.0,
        )

        self.assertEqual(websocket.closed_with, WsCloseCode.UNAUTHENTICATED)


if __name__ == "__main__":
    unittest.main()
