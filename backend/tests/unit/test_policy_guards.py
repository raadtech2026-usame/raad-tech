"""Unit tests for `interfaces.http.policy_guards` — the CR-1 (`SubscriptionAccessPolicy`) and
D5 (`VideoAccessPolicy`) enforcement points. Stdlib `unittest` — no `pytest` (not an approved
dependency). Fakes are bound directly into a real `core.di.container.Container`, keyed by the
real application-service/port *types* `policy_guards` resolves — the same pattern
`test_notification_subscribers.py` already establishes for an analogous cross-module
orchestration file.

Covers the safety-critical invariants `.claude/rules/testing.md` #3 names — CR-1 and D5 —
at their actual enforcement point. The underlying `SubscriptionAccessPolicy`/`VideoAccessPolicy`/
`TrackingVisibilityPolicy` decision objects already have thorough unit tests
(`test_core_subscription_access_policy.py`, `test_core_video_access_policy.py`,
`test_tracking_domain_policies.py`); this file exercises the orchestration glue around them that
had no test at all: `resolve_cr1_decision`/`enforce_cr1`'s D4/CR-1 `safety_override`
reconciliation and 404-over-403 non-owner handling, `find_owned_student_id_for_vehicle`'s
ownership resolution, `resolve_tracking_decision`'s four-input composition for both Parent and
Org-Admin callers, and `resolve_d5_decision`/`enforce_d5`. Also regression-covers the error-code
fix in `core/errors/exceptions.py`: `enforce_cr1` must raise `ParentAccessDeniedError` carrying
the policy's own `reason`/`required_action`, and `enforce_d5` must raise `VideoForbiddenError`
— not a generic `AuthorizationError` with the code folded into the message string.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from raad.core.di.container import Container
from raad.core.errors.exceptions import (
    NotFoundError,
    ParentAccessDeniedError,
    VideoForbiddenError,
)
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.resolver import ScopeResolver
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http import policy_guards
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import (
    DeviceApplicationService,
    VehicleApplicationService,
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
OTHER_ORG_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


@dataclass(frozen=True)
class _ParentDTO:
    id: str
    has_video_live_access: bool = False
    has_video_playback_access: bool = False


@dataclass(frozen=True)
class _StudentLinkDTO:
    student_id: str


@dataclass(frozen=True)
class _AssignmentDTO:
    status: str
    vehicle_id: str | None = None


@dataclass(frozen=True)
class _SubscriptionDTO:
    status: str


class FakeParentService:
    def __init__(self, parent_by_user_id: dict[str, _ParentDTO]) -> None:
        self._by_user_id = parent_by_user_id

    async def get_parent_by_user_id(self, user_id, *, uow):
        return self._by_user_id.get(user_id)

    async def get_parent_by_id(self, query, *, uow):
        for parent in self._by_user_id.values():
            if parent.id == query.parent_id:
                return parent
        raise NotFoundError(f"Parent {query.parent_id} not found.")


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


class FakeBillingService:
    def __init__(self, subscription: _SubscriptionDTO | None) -> None:
        self._subscription = subscription

    async def get_active_subscription_for_organization(self, organization_id, *, uow):
        return self._subscription


class FakeScopeResolver(ScopeResolver):
    def __init__(self, scope: TenantRegionScope) -> None:
        self._scope = scope

    async def effective_org_scope(self, principal: Principal) -> TenantRegionScope:
        return self._scope


@dataclass(frozen=True)
class _VehicleDTO:
    organization_id: str


@dataclass(frozen=True)
class _PositionDTO:
    trip_id: str | None


@dataclass(frozen=True)
class _TripStatusDTO:
    status: str


class FakeVehicleService:
    def __init__(self, vehicles_by_id: dict[str, _VehicleDTO]) -> None:
        self._by_id = vehicles_by_id

    async def get_vehicle_by_id(self, query, *, uow):
        vehicle = self._by_id.get(query.vehicle_id)
        if vehicle is None:
            raise NotFoundError(f"Vehicle {query.vehicle_id} not found.")
        return vehicle


@dataclass(frozen=True)
class _DeviceAssignmentDTO:
    vehicle_id: str


class FakeDeviceService:
    """ADR-0026 §3 - `find_owned_student_id_for_device`'s own `DeviceApplicationService`
    dependency."""

    def __init__(self, assignment_by_device: dict[str, _DeviceAssignmentDTO | None]) -> None:
        self._by_device = assignment_by_device

    async def get_active_vehicle_assignment_for_device(self, device_id, *, uow):
        return self._by_device.get(device_id)


class FakeTrackingService:
    def __init__(
        self, position_by_vehicle: dict[str, _PositionDTO | None] | None = None
    ) -> None:
        self._by_vehicle = position_by_vehicle or {}

    async def get_current_vehicle_position(self, query):
        return self._by_vehicle.get(query.vehicle_id)


class RedisUnboundTrackingService:
    """Mirrors `TrackingApplicationService.get_current_vehicle_position`'s real behavior when
    no `LatestPositionPort` is bound at all — raises `NotImplementedError`, never returns a
    fake position."""

    async def get_current_vehicle_position(self, query):
        raise NotImplementedError("No LatestPositionPort is bound.")


class FakeTripService:
    def __init__(self, trip_by_id: dict[str, _TripStatusDTO] | None = None) -> None:
        self._by_id = trip_by_id or {}

    async def get_trip_by_id(self, query, *, uow):
        return self._by_id[query.trip_id]


def make_container(
    *,
    parent_id: str = "parent-1",
    parent_user_id: str = "user-1",
    has_video_live_access: bool = False,
    has_video_playback_access: bool = False,
    children: list[str] | None = None,
    assignments: dict[str, _AssignmentDTO | None] | None = None,
    subscription: _SubscriptionDTO | None = None,
    scope: TenantRegionScope = TenantRegionScope(organization_ids=frozenset({ORG_ID})),
    vehicles: dict[str, _VehicleDTO] | None = None,
    devices: dict[str, _DeviceAssignmentDTO | None] | None = None,
    positions: dict[str, _PositionDTO | None] | None = None,
    trips: dict[str, _TripStatusDTO] | None = None,
    tracking_service: object | None = None,
) -> Container:
    container = Container()
    container.bind_singleton(
        ParentApplicationService,
        FakeParentService(
            {
                parent_user_id: _ParentDTO(
                    id=parent_id,
                    has_video_live_access=has_video_live_access,
                    has_video_playback_access=has_video_playback_access,
                )
            }
        ),
    )
    container.bind_singleton(
        StudentParentApplicationService,
        FakeStudentParentService(
            {parent_id: [_StudentLinkDTO(student_id=s) for s in (children or [])]}
        ),
    )
    container.bind_singleton(
        StudentAssignmentApplicationService,
        FakeStudentAssignmentService(assignments or {}),
    )
    container.bind_singleton(BillingApplicationService, FakeBillingService(subscription))
    container.bind_singleton(ScopeResolver, FakeScopeResolver(scope))
    container.bind_singleton(VehicleApplicationService, FakeVehicleService(vehicles or {}))
    container.bind_singleton(DeviceApplicationService, FakeDeviceService(devices or {}))
    container.bind_singleton(
        TrackingApplicationService, tracking_service or FakeTrackingService(positions)
    )
    container.bind_singleton(TripApplicationService, FakeTripService(trips))

    for uow_type in (
        TransportOpsUnitOfWork,
        BillingUnitOfWork,
        FleetDeviceUnitOfWork,
    ):
        container.bind_singleton(uow_type, object())

    return container


PARENT = Principal(user_id="user-1", role=Role.PARENT, org_id=ORG_ID)
ORG_ADMIN = Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=ORG_ID)


class ResolveCr1DecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_owning_parent_raises_not_found_not_forbidden(self) -> None:
        """404-over-403 (LLD §14.3): CR-1 only governs a Parent's *known-own* child, so a
        stranger's student id must not confirm existence via a 403."""
        container = make_container(children=[])
        with self.assertRaises(NotFoundError):
            await policy_guards.resolve_cr1_decision(
                principal=PARENT, student_id="s1", container=container
            )

    async def test_inactive_assignment_denies_regardless_of_subscription_state(self) -> None:
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="removed")},
            subscription=_SubscriptionDTO(status="active"),
        )
        decision = await policy_guards.resolve_cr1_decision(
            principal=PARENT, student_id="s1", container=container
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ASSIGNMENT_INACTIVE")
        self.assertIsNone(decision.required_action)

    async def test_no_assignment_at_all_denies_as_inactive(self) -> None:
        container = make_container(children=["s1"], assignments={})
        decision = await policy_guards.resolve_cr1_decision(
            principal=PARENT, student_id="s1", container=container
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ASSIGNMENT_INACTIVE")

    async def test_active_assignment_with_active_subscription_grants(self) -> None:
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active")},
            subscription=_SubscriptionDTO(status="active"),
        )
        decision = await policy_guards.resolve_cr1_decision(
            principal=PARENT, student_id="s1", container=container
        )
        self.assertTrue(decision.allowed)

    async def test_active_assignment_with_no_subscription_denies_with_redirect_action(
        self,
    ) -> None:
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active")},
            subscription=None,
        )
        decision = await policy_guards.resolve_cr1_decision(
            principal=PARENT, student_id="s1", container=container
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SUBSCRIPTION_EXPIRED")
        self.assertEqual(decision.required_action, "REDIRECT_TO_PAYMENT")

    async def test_safety_override_grants_active_assignment_even_with_lapsed_subscription(
        self,
    ) -> None:
        """D4/CR-1 reconciliation (ADR-0006): live GPS during an active trip is never
        billing-gated, so `safety_override=True` must short-circuit the subscription check
        entirely for an ACTIVE assignment."""
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active")},
            subscription=None,
        )
        decision = await policy_guards.resolve_cr1_decision(
            principal=PARENT,
            student_id="s1",
            container=container,
            safety_override=True,
        )
        self.assertTrue(decision.allowed)

    async def test_safety_override_does_not_bypass_the_assignment_gate(self) -> None:
        """Business rule 3 (highest precedence): `safety_override` only ever applies to an
        already-ACTIVE assignment — it must not grant access for a removed/inactive one."""
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="removed")},
        )
        decision = await policy_guards.resolve_cr1_decision(
            principal=PARENT,
            student_id="s1",
            container=container,
            safety_override=True,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ASSIGNMENT_INACTIVE")


class EnforceCr1Tests(unittest.IsolatedAsyncioTestCase):
    async def test_non_parent_role_is_a_no_op(self) -> None:
        """LLD SS5.4: "Org Admin, Driver, and RAAD staff access is unaffected" — must not even
        evaluate the policy (an empty container would raise `LookupError` if it tried)."""
        container = Container()
        await policy_guards.enforce_cr1(
            principal=ORG_ADMIN, student_id="s1", container=container
        )

    async def test_denied_raises_parent_access_denied_error_with_code_reason_and_action(
        self,
    ) -> None:
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active")},
            subscription=None,
        )
        with self.assertRaises(ParentAccessDeniedError) as ctx:
            await policy_guards.enforce_cr1(
                principal=PARENT, student_id="s1", container=container
            )
        self.assertEqual(ctx.exception.code, "PARENT_ACCESS_DENIED")
        self.assertEqual(ctx.exception.reason, "SUBSCRIPTION_EXPIRED")
        self.assertEqual(ctx.exception.required_action, "REDIRECT_TO_PAYMENT")

    async def test_granted_does_not_raise(self) -> None:
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active")},
            subscription=_SubscriptionDTO(status="active"),
        )
        await policy_guards.enforce_cr1(
            principal=PARENT, student_id="s1", container=container
        )


class FindOwnedStudentIdForVehicleTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_child_assigned_to_the_vehicle(self) -> None:
        container = make_container(
            children=["s1", "s2"],
            assignments={
                "s1": _AssignmentDTO(status="active", vehicle_id="veh-other"),
                "s2": _AssignmentDTO(status="active", vehicle_id="veh-1"),
            },
        )
        student_id = await policy_guards.find_owned_student_id_for_vehicle(
            principal=PARENT, vehicle_id="veh-1", container=container
        )
        self.assertEqual(student_id, "s2")

    async def test_returns_none_when_no_child_is_assigned_to_the_vehicle(self) -> None:
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active", vehicle_id="veh-other")},
        )
        student_id = await policy_guards.find_owned_student_id_for_vehicle(
            principal=PARENT, vehicle_id="veh-1", container=container
        )
        self.assertIsNone(student_id)

    async def test_returns_none_when_child_has_no_active_assignment_at_all(self) -> None:
        container = make_container(children=["s1"], assignments={})
        student_id = await policy_guards.find_owned_student_id_for_vehicle(
            principal=PARENT, vehicle_id="veh-1", container=container
        )
        self.assertIsNone(student_id)


class ResolveTrackingDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_parent_with_no_owned_vehicle_is_denied(self) -> None:
        container = make_container(children=[])
        decision = await policy_guards.resolve_tracking_decision(
            principal=PARENT,
            organization_id=ORG_ID,
            vehicle_id="veh-1",
            is_trip_active=True,
            container=container,
        )
        self.assertFalse(decision.allowed)

    async def test_parent_with_active_trip_and_active_assignment_is_granted(self) -> None:
        """The D4-protected scenario itself: live GPS during an active trip, even for an
        organization with no active subscription at all — the safety override must flow
        through `resolve_tracking_decision`'s own `is_trip_active`-driven `safety_override`."""
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active", vehicle_id="veh-1")},
            subscription=None,
        )
        decision = await policy_guards.resolve_tracking_decision(
            principal=PARENT,
            organization_id=ORG_ID,
            vehicle_id="veh-1",
            is_trip_active=True,
            container=container,
        )
        self.assertTrue(decision.allowed)

    async def test_parent_outside_active_trip_with_lapsed_subscription_is_denied(self) -> None:
        """Outside an active trip, CR-1's normal subscription gate applies (flutter.md #4:
        never a stale "live" indicator outside active trips)."""
        container = make_container(
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active", vehicle_id="veh-1")},
            subscription=None,
        )
        decision = await policy_guards.resolve_tracking_decision(
            principal=PARENT,
            organization_id=ORG_ID,
            vehicle_id="veh-1",
            is_trip_active=False,
            container=container,
        )
        self.assertFalse(decision.allowed)

    async def test_org_admin_within_scope_is_granted(self) -> None:
        container = make_container(
            scope=TenantRegionScope(organization_ids=frozenset({ORG_ID}))
        )
        decision = await policy_guards.resolve_tracking_decision(
            principal=ORG_ADMIN,
            organization_id=ORG_ID,
            vehicle_id="veh-1",
            is_trip_active=False,
            container=container,
        )
        self.assertTrue(decision.allowed)

    async def test_org_admin_outside_scope_is_denied(self) -> None:
        container = make_container(
            scope=TenantRegionScope(organization_ids=frozenset({OTHER_ORG_ID}))
        )
        decision = await policy_guards.resolve_tracking_decision(
            principal=ORG_ADMIN,
            organization_id=ORG_ID,
            vehicle_id="veh-1",
            is_trip_active=False,
            container=container,
        )
        self.assertFalse(decision.allowed)


class ResolveAndEnforceD5Tests(unittest.IsolatedAsyncioTestCase):
    """D5 (`.claude/rules/jt1078.md` #1) plus its ADR-0026 parent-permission extension. Every
    Parent test below wires a *real* owned-device/child chain unless the test is specifically
    about the absence of one — `device-1` -> `veh-1` -> `s1`, `s1` assigned to `parent-1`."""

    async def test_org_admin_within_own_org_is_granted(self) -> None:
        container = make_container(
            scope=TenantRegionScope(organization_ids=frozenset({ORG_ID}))
        )
        decision = await policy_guards.resolve_d5_decision(
            principal=ORG_ADMIN,
            device_organization_id=ORG_ID,
            device_id="device-1",
            purpose="live",
            container=container,
        )
        self.assertTrue(decision.allowed)
        await policy_guards.enforce_d5(
            principal=ORG_ADMIN,
            device_organization_id=ORG_ID,
            device_id="device-1",
            purpose="live",
            container=container,
        )

    async def test_org_admin_outside_own_org_raises_video_forbidden_error(self) -> None:
        container = make_container(
            scope=TenantRegionScope(organization_ids=frozenset({ORG_ID}))
        )
        with self.assertRaises(VideoForbiddenError) as ctx:
            await policy_guards.enforce_d5(
                principal=ORG_ADMIN,
                device_organization_id=OTHER_ORG_ID,
                device_id="device-1",
                purpose="live",
                container=container,
            )
        self.assertEqual(ctx.exception.code, "VIDEO_FORBIDDEN")

    async def test_driver_is_denied_regardless_of_scope(self) -> None:
        """ADR-0026 is Parent-only - Driver's own eligibility is unchanged."""
        driver = Principal(user_id="driver-1", role=Role.DRIVER, org_id=ORG_ID)
        container = make_container(
            scope=TenantRegionScope(organization_ids=frozenset({ORG_ID}))
        )
        with self.assertRaises(VideoForbiddenError):
            await policy_guards.enforce_d5(
                principal=driver,
                device_organization_id=ORG_ID,
                device_id="device-1",
                purpose="live",
                container=container,
            )

    async def test_parent_owning_neither_device_nor_child_raises_not_found_not_forbidden(
        self,
    ) -> None:
        """404-over-403 (ADR-0026 §3, mirroring CR-1's own precedent): a parent with zero
        ownership relationship to the device must not learn it exists via a 403 - even one
        holding the permission flag."""
        container = make_container(
            has_video_live_access=True, children=[], devices={"device-1": None}
        )
        with self.assertRaises(NotFoundError):
            await policy_guards.resolve_d5_decision(
                principal=PARENT,
                device_organization_id=ORG_ID,
                device_id="device-1",
                purpose="live",
                container=container,
            )

    async def test_parent_owning_device_but_lacking_permission_is_forbidden(self) -> None:
        container = make_container(
            has_video_live_access=False,
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active", vehicle_id="veh-1")},
            devices={"device-1": _DeviceAssignmentDTO(vehicle_id="veh-1")},
        )
        decision = await policy_guards.resolve_d5_decision(
            principal=PARENT,
            device_organization_id=ORG_ID,
            device_id="device-1",
            purpose="live",
            container=container,
        )
        self.assertFalse(decision.allowed)
        with self.assertRaises(VideoForbiddenError):
            await policy_guards.enforce_d5(
                principal=PARENT,
                device_organization_id=ORG_ID,
                device_id="device-1",
                purpose="live",
                container=container,
            )

    async def test_parent_owning_device_and_granted_live_access_is_allowed(self) -> None:
        container = make_container(
            has_video_live_access=True,
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active", vehicle_id="veh-1")},
            devices={"device-1": _DeviceAssignmentDTO(vehicle_id="veh-1")},
        )
        decision = await policy_guards.resolve_d5_decision(
            principal=PARENT,
            device_organization_id=ORG_ID,
            device_id="device-1",
            purpose="live",
            container=container,
        )
        self.assertTrue(decision.allowed)

    async def test_live_access_does_not_grant_playback(self) -> None:
        """ADR-0026 §3: live and playback are independently checked - one flag must never
        satisfy the other purpose."""
        container = make_container(
            has_video_live_access=True,
            has_video_playback_access=False,
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active", vehicle_id="veh-1")},
            devices={"device-1": _DeviceAssignmentDTO(vehicle_id="veh-1")},
        )
        decision = await policy_guards.resolve_d5_decision(
            principal=PARENT,
            device_organization_id=ORG_ID,
            device_id="device-1",
            purpose="playback",
            container=container,
        )
        self.assertFalse(decision.allowed)

    async def test_parent_granted_playback_access_is_allowed_for_playback(self) -> None:
        container = make_container(
            has_video_playback_access=True,
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active", vehicle_id="veh-1")},
            devices={"device-1": _DeviceAssignmentDTO(vehicle_id="veh-1")},
        )
        decision = await policy_guards.resolve_d5_decision(
            principal=PARENT,
            device_organization_id=ORG_ID,
            device_id="device-1",
            purpose="playback",
            container=container,
        )
        self.assertTrue(decision.allowed)

    async def test_parent_owning_a_different_childs_device_is_not_found(self) -> None:
        """The device is real and assigned, but to a vehicle none of *this* parent's children
        rides - must still be 404, not 403, matching the "not owned at all" case."""
        container = make_container(
            has_video_live_access=True,
            children=["s1"],
            assignments={"s1": _AssignmentDTO(status="active", vehicle_id="veh-OTHER")},
            devices={"device-1": _DeviceAssignmentDTO(vehicle_id="veh-1")},
        )
        with self.assertRaises(NotFoundError):
            await policy_guards.resolve_d5_decision(
                principal=PARENT,
                device_organization_id=ORG_ID,
                device_id="device-1",
                purpose="live",
                container=container,
            )


class ResolveVehicleTrackingContextTests(unittest.IsolatedAsyncioTestCase):
    """`resolve_vehicle_tracking_context` — built for `/ws/tracking`'s subscribe flow
    (WebSocket phase), which must resolve `(organization_id, is_trip_active)` even before any
    position has ever arrived for a vehicle, unlike `GET /tracking/vehicles/{id}/latest`."""

    async def test_unknown_vehicle_returns_none(self) -> None:
        container = make_container(vehicles={})
        result = await policy_guards.resolve_vehicle_tracking_context(
            vehicle_id="veh-1", container=container
        )
        self.assertIsNone(result)

    async def test_vehicle_with_no_cached_position_resolves_org_id_with_inactive_trip(
        self,
    ) -> None:
        """No live position yet (fresh vehicle, or Redis simply hasn't seen one) — `is_trip_
        active` degrades to `False`, the conservative direction, not a crash."""
        container = make_container(
            vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)}, positions={}
        )
        result = await policy_guards.resolve_vehicle_tracking_context(
            vehicle_id="veh-1", container=container
        )
        self.assertEqual(result, (ORG_ID, False))

    async def test_no_latest_position_port_bound_degrades_to_inactive_trip_not_a_crash(
        self,
    ) -> None:
        """Mirrors `GET /tracking/vehicles/{id}/latest`'s own documented "no LatestPositionPort
        bound -> NotImplementedError" case — but this helper must not let that propagate and
        abort a subscribe attempt; it degrades to `is_trip_active=False` instead (never the
        permissive direction for a Parent caller)."""
        container = make_container(
            vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)},
            tracking_service=RedisUnboundTrackingService(),
        )
        result = await policy_guards.resolve_vehicle_tracking_context(
            vehicle_id="veh-1", container=container
        )
        self.assertEqual(result, (ORG_ID, False))

    async def test_position_with_in_progress_trip_resolves_is_trip_active_true(self) -> None:
        container = make_container(
            vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)},
            positions={"veh-1": _PositionDTO(trip_id="trip-1")},
            trips={"trip-1": _TripStatusDTO(status="in_progress")},
        )
        result = await policy_guards.resolve_vehicle_tracking_context(
            vehicle_id="veh-1", container=container
        )
        self.assertEqual(result, (ORG_ID, True))

    async def test_position_with_completed_trip_resolves_is_trip_active_false(self) -> None:
        container = make_container(
            vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)},
            positions={"veh-1": _PositionDTO(trip_id="trip-1")},
            trips={"trip-1": _TripStatusDTO(status="completed")},
        )
        result = await policy_guards.resolve_vehicle_tracking_context(
            vehicle_id="veh-1", container=container
        )
        self.assertEqual(result, (ORG_ID, False))

    async def test_position_with_no_trip_id_resolves_is_trip_active_false(self) -> None:
        container = make_container(
            vehicles={"veh-1": _VehicleDTO(organization_id=ORG_ID)},
            positions={"veh-1": _PositionDTO(trip_id=None)},
        )
        result = await policy_guards.resolve_vehicle_tracking_context(
            vehicle_id="veh-1", container=container
        )
        self.assertEqual(result, (ORG_ID, False))


if __name__ == "__main__":
    unittest.main()
