"""Unit tests for `modules.notifications.events.subscribers` (Backend Stabilization phase).
Stdlib `unittest` — no `pytest` (not an approved dependency). Fakes are bound directly into a
real `core.di.container.Container`, keyed by the real application-service/UoW *types*
`_NotificationFanOut` resolves — `Container.resolve` does a plain type-keyed dict lookup with no
`isinstance` enforcement, so a duck-typed fake registers exactly like a real service would,
without needing to construct full domain aggregates through their own constructors. This tests
the actual recipient-resolution + CR-1-gating logic real dependencies would exercise, at the
service-boundary `_NotificationFanOut` actually depends on.

Covers the safety-critical CR-1 gating this file's own module docstring documents
(`.claude/rules/testing.md` #3: CR-1 requires explicit regression tests): `ORGANIZATION_PAYS`
always grants, `PARENT_PAYS` with an active subscription grants, `PARENT_PAYS` with no/lapsed
subscription withholds the notification entirely (not a raised error — CR-1 denial for a
*notification* means "don't send it", unlike an HTTP route's 403); no active assignment for the
vehicle means zero notifications; the same parent linked to two students on the same vehicle is
notified once, not twice; and the two geofence `EventProcessor`s correctly resolve `vehicle_id`
from `trip_id` first.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.services import NotificationApplicationService
from raad.modules.notifications.events.subscribers import (
    TripEndedNotifier,
    TripStartedNotifier,
    VehicleApproachingStopNotifier,
    _NotificationFanOut,
)
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.services import OrganizationApplicationService
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.services import (
    ParentApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
    TripApplicationService,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


@dataclass(frozen=True)
class _AssignmentDTO:
    student_id: str
    status: str
    vehicle_id: str | None


@dataclass(frozen=True)
class _ParentLinkDTO:
    parent_id: str


@dataclass(frozen=True)
class _ParentDTO:
    user_id: str


@dataclass(frozen=True)
class _OrganizationDTO:
    billing_model: str


@dataclass(frozen=True)
class _SubscriptionDTO:
    status: str


@dataclass(frozen=True)
class _TripDTO:
    vehicle_id: str


class FakeStudentAssignmentService:
    def __init__(self, assignments: list[_AssignmentDTO]) -> None:
        self._assignments = assignments

    async def list_student_assignments(self, query, *, uow):
        return list(self._assignments)


class FakeStudentParentService:
    def __init__(self, links_by_student: dict[str, list[_ParentLinkDTO]]) -> None:
        self._links_by_student = links_by_student

    async def list_parents_for_student(self, query, *, uow):
        return list(self._links_by_student.get(query.student_id, []))


class FakeParentService:
    def __init__(self, parents_by_id: dict[str, _ParentDTO]) -> None:
        self._parents_by_id = parents_by_id

    async def get_parent_by_id(self, query, *, uow):
        return self._parents_by_id[query.parent_id]


class FakeOrganizationService:
    def __init__(self, billing_model: str) -> None:
        self._billing_model = billing_model

    async def get_organization_by_id(self, query, *, uow):
        return _OrganizationDTO(billing_model=self._billing_model)


class FakeBillingService:
    def __init__(self, subscription: _SubscriptionDTO | None) -> None:
        self._subscription = subscription

    async def get_active_subscription_for_subscriber(self, subscriber_type, subscriber_id, *, uow):
        return self._subscription


class FakeTripService:
    def __init__(self, vehicle_id: str) -> None:
        self._vehicle_id = vehicle_id

    async def get_trip_by_id(self, query, *, uow):
        return _TripDTO(vehicle_id=self._vehicle_id)


@dataclass
class RecordingNotificationService:
    created: list[dict[str, Any]] = field(default_factory=list)

    async def create_notification(self, command, *, uow):
        self.created.append(
            {
                "recipient_user_id": command.recipient_user_id,
                "type": command.type,
                "organization_id": command.organization_id,
            }
        )
        return None


def make_container(
    *,
    assignments: list[_AssignmentDTO],
    links_by_student: dict[str, list[_ParentLinkDTO]],
    parents_by_id: dict[str, _ParentDTO],
    billing_model: str = "organization_pays",
    subscription: _SubscriptionDTO | None = _SubscriptionDTO(status="active"),
    trip_vehicle_id: str | None = None,
) -> tuple[Container, RecordingNotificationService]:
    container = Container()
    container.bind_singleton(
        StudentAssignmentApplicationService, FakeStudentAssignmentService(assignments)
    )
    container.bind_singleton(
        StudentParentApplicationService, FakeStudentParentService(links_by_student)
    )
    container.bind_singleton(ParentApplicationService, FakeParentService(parents_by_id))
    container.bind_singleton(
        OrganizationApplicationService, FakeOrganizationService(billing_model)
    )
    container.bind_singleton(BillingApplicationService, FakeBillingService(subscription))
    notification_service = RecordingNotificationService()
    container.bind_singleton(NotificationApplicationService, notification_service)
    if trip_vehicle_id is not None:
        container.bind_singleton(TripApplicationService, FakeTripService(trip_vehicle_id))

    # UoW types are resolved but never actually used by the fakes above (they don't open
    # `async with uow:` themselves) — bound to inert sentinels only so `container.resolve`
    # doesn't raise `LookupError`.
    for uow_type in (
        TransportOpsUnitOfWork,
        OrganizationUnitOfWork,
        BillingUnitOfWork,
        NotificationsUnitOfWork,
    ):
        container.bind_singleton(uow_type, object())

    return container, notification_service


def make_event(
    *,
    event_type: str = "TripStarted",
    aggregate_id: str = "01J8Z3K9G6X8YV5T4N2R7QW3TR",
    payload: dict[str, Any],
) -> DomainEvent:
    return DomainEvent(
        event_id="evt-1",
        event_type=event_type,
        version=1,
        occurred_at=datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc),
        org_id=VALID_ORG_ULID,
        correlation_id=None,
        payload=payload,
        aggregate_type="Trip",
        aggregate_id=aggregate_id,
    )


class NotifyVehicleWatchersTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_active_assignment_notifies_nobody(self) -> None:
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="removed", vehicle_id="veh-1")
            ],
            links_by_student={},
            parents_by_id={},
        )
        fan_out = _NotificationFanOut(container)
        await fan_out.notify_vehicle_watchers(
            vehicle_id="veh-1",
            organization_id=VALID_ORG_ULID,
            type="trip_started",
            title="t",
            body="b",
            data=None,
            trip_id="trip-1",
        )
        self.assertEqual(notifications.created, [])

    async def test_active_assignment_organization_pays_notifies(self) -> None:
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="active", vehicle_id="veh-1")
            ],
            links_by_student={"s1": [_ParentLinkDTO(parent_id="p1")]},
            parents_by_id={"p1": _ParentDTO(user_id="user-1")},
            billing_model="organization_pays",
        )
        fan_out = _NotificationFanOut(container)
        await fan_out.notify_vehicle_watchers(
            vehicle_id="veh-1",
            organization_id=VALID_ORG_ULID,
            type="trip_started",
            title="t",
            body="b",
            data=None,
            trip_id="trip-1",
        )
        self.assertEqual(len(notifications.created), 1)
        self.assertEqual(notifications.created[0]["recipient_user_id"], "user-1")

    async def test_parent_pays_with_active_subscription_notifies(self) -> None:
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="active", vehicle_id="veh-1")
            ],
            links_by_student={"s1": [_ParentLinkDTO(parent_id="p1")]},
            parents_by_id={"p1": _ParentDTO(user_id="user-1")},
            billing_model="parent_pays",
            subscription=_SubscriptionDTO(status="active"),
        )
        fan_out = _NotificationFanOut(container)
        await fan_out.notify_vehicle_watchers(
            vehicle_id="veh-1",
            organization_id=VALID_ORG_ULID,
            type="trip_started",
            title="t",
            body="b",
            data=None,
            trip_id="trip-1",
        )
        self.assertEqual(len(notifications.created), 1)

    async def test_parent_pays_with_no_subscription_withholds_notification(self) -> None:
        """CR-1 (`.claude/rules/testing.md` #3, safety-critical). A `PARENT_PAYS` parent with
        no active subscription must not receive the notification — withheld silently, not a
        raised error, matching a notification's own "don't send it" semantics."""
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="active", vehicle_id="veh-1")
            ],
            links_by_student={"s1": [_ParentLinkDTO(parent_id="p1")]},
            parents_by_id={"p1": _ParentDTO(user_id="user-1")},
            billing_model="parent_pays",
            subscription=None,
        )
        fan_out = _NotificationFanOut(container)
        await fan_out.notify_vehicle_watchers(
            vehicle_id="veh-1",
            organization_id=VALID_ORG_ULID,
            type="trip_started",
            title="t",
            body="b",
            data=None,
            trip_id="trip-1",
        )
        self.assertEqual(notifications.created, [])

    async def test_parent_pays_with_expired_subscription_withholds_notification(self) -> None:
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="active", vehicle_id="veh-1")
            ],
            links_by_student={"s1": [_ParentLinkDTO(parent_id="p1")]},
            parents_by_id={"p1": _ParentDTO(user_id="user-1")},
            billing_model="parent_pays",
            subscription=_SubscriptionDTO(status="expired"),
        )
        fan_out = _NotificationFanOut(container)
        await fan_out.notify_vehicle_watchers(
            vehicle_id="veh-1",
            organization_id=VALID_ORG_ULID,
            type="trip_started",
            title="t",
            body="b",
            data=None,
            trip_id="trip-1",
        )
        self.assertEqual(notifications.created, [])

    async def test_same_parent_two_students_notified_once(self) -> None:
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="active", vehicle_id="veh-1"),
                _AssignmentDTO(student_id="s2", status="active", vehicle_id="veh-1"),
            ],
            links_by_student={
                "s1": [_ParentLinkDTO(parent_id="p1")],
                "s2": [_ParentLinkDTO(parent_id="p1")],
            },
            parents_by_id={"p1": _ParentDTO(user_id="user-1")},
            billing_model="organization_pays",
        )
        fan_out = _NotificationFanOut(container)
        await fan_out.notify_vehicle_watchers(
            vehicle_id="veh-1",
            organization_id=VALID_ORG_ULID,
            type="trip_started",
            title="t",
            body="b",
            data=None,
            trip_id="trip-1",
        )
        self.assertEqual(len(notifications.created), 1)

    async def test_assignment_for_a_different_vehicle_is_ignored(self) -> None:
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="active", vehicle_id="veh-OTHER")
            ],
            links_by_student={"s1": [_ParentLinkDTO(parent_id="p1")]},
            parents_by_id={"p1": _ParentDTO(user_id="user-1")},
        )
        fan_out = _NotificationFanOut(container)
        await fan_out.notify_vehicle_watchers(
            vehicle_id="veh-1",
            organization_id=VALID_ORG_ULID,
            type="trip_started",
            title="t",
            body="b",
            data=None,
            trip_id="trip-1",
        )
        self.assertEqual(notifications.created, [])


class EventProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_trip_started_notifier_uses_vehicle_id_from_payload(self) -> None:
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="active", vehicle_id="veh-1")
            ],
            links_by_student={"s1": [_ParentLinkDTO(parent_id="p1")]},
            parents_by_id={"p1": _ParentDTO(user_id="user-1")},
        )
        processor = TripStartedNotifier(_NotificationFanOut(container))
        event = make_event(
            event_type="TripStarted", payload={"vehicle_id": "veh-1", "actor_id": None}
        )
        await processor.process(event)
        self.assertEqual(len(notifications.created), 1)
        self.assertEqual(notifications.created[0]["type"], "trip_started")

    async def test_trip_ended_notifier_uses_trip_completed_type(self) -> None:
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="active", vehicle_id="veh-1")
            ],
            links_by_student={"s1": [_ParentLinkDTO(parent_id="p1")]},
            parents_by_id={"p1": _ParentDTO(user_id="user-1")},
        )
        processor = TripEndedNotifier(_NotificationFanOut(container))
        event = make_event(
            event_type="TripEnded", payload={"vehicle_id": "veh-1", "actor_id": None}
        )
        await processor.process(event)
        self.assertEqual(notifications.created[0]["type"], "trip_completed")

    async def test_approaching_stop_notifier_resolves_vehicle_id_from_trip(self) -> None:
        container, notifications = make_container(
            assignments=[
                _AssignmentDTO(student_id="s1", status="active", vehicle_id="veh-1")
            ],
            links_by_student={"s1": [_ParentLinkDTO(parent_id="p1")]},
            parents_by_id={"p1": _ParentDTO(user_id="user-1")},
            trip_vehicle_id="veh-1",
        )
        processor = VehicleApproachingStopNotifier(_NotificationFanOut(container))
        event = make_event(
            event_type="VehicleApproachingStop",
            aggregate_id="01J8Z3K9G6X8YV5T4N2R7QW3GC",
            payload={"trip_id": "trip-1", "stop_id": "stop-1"},
        )
        await processor.process(event)
        self.assertEqual(len(notifications.created), 1)
        self.assertEqual(notifications.created[0]["type"], "approaching_stop")


if __name__ == "__main__":
    unittest.main()
