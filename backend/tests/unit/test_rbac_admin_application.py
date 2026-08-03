"""Application-layer tests for `iam.PermissionApplicationService` and `organization.
ScopeAssignmentApplicationService` — Priority 1 Item 6 (`PROJECT_STATUS.md`, RBAC grant/revoke
route). Neither service had any unit test coverage before this item, despite existing since the
Backend Stabilization phase — a real, pre-existing gap this item's own new HTTP routes made
worth closing, not just leaving covered only by (now-added) live/router-level checks.

Stdlib `unittest` — no `pytest`. In-memory fakes, mirroring `test_iam_application.py`'s
`FakeIamUnitOfWork` pattern.
"""

from __future__ import annotations

import unittest

from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.iam.application.commands import (
    GrantRolePermissionCommand,
    RevokeRolePermissionCommand,
)
from raad.modules.iam.application.services import PermissionApplicationService
from raad.modules.iam.domain import events as iam_events
from raad.modules.organization.application.commands import (
    GrantRegionAssignmentCommand,
    GrantSupportAssignmentCommand,
    RevokeRegionAssignmentCommand,
    RevokeSupportAssignmentCommand,
)
from raad.modules.organization.application.services import (
    ScopeAssignmentApplicationService,
)
from raad.modules.organization.domain import events as org_events


class FixedClock(Clock):
    def __init__(self, now):  # noqa: ANN001
        self._now = now

    def now(self):  # noqa: ANN001
        return self._now


def make_actor() -> Principal:
    return Principal(user_id="founder-1", role=Role.FOUNDER, org_id=None)


from datetime import datetime, timezone

_NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)


class FakeRolePermissionRepository:
    def __init__(self) -> None:
        self._grants: set[tuple[Role, str]] = set()

    async def list_permissions_for_role(self, role: Role) -> frozenset[str]:
        return frozenset(p for r, p in self._grants if r == role)

    async def grant(self, role: Role, permission: str) -> None:
        self._grants.add((role, permission))

    async def revoke(self, role: Role, permission: str) -> None:
        self._grants.discard((role, permission))


class FakeIamUow:
    def __init__(self) -> None:
        self.role_permissions = FakeRolePermissionRepository()
        self.recorded_events = []
        self.commit_count = 0

    def record_events(self, events) -> None:  # noqa: ANN001
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> "FakeIamUow":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        pass


class PermissionApplicationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_grant_then_list_round_trips(self) -> None:
        service = PermissionApplicationService(clock=FixedClock(_NOW))
        uow = FakeIamUow()
        await service.grant_role_permission(
            GrantRolePermissionCommand(
                role=Role.SUPPORT_STAFF,
                permission="fleet_device.devices.read",
                actor=make_actor(),
            ),
            uow=uow,
        )
        permissions = await service.list_permissions_for_role(
            Role.SUPPORT_STAFF, uow=uow
        )
        self.assertIn("fleet_device.devices.read", permissions)
        self.assertEqual(uow.commit_count, 1)

    async def test_grant_records_role_permission_granted_event(self) -> None:
        service = PermissionApplicationService(clock=FixedClock(_NOW))
        uow = FakeIamUow()
        await service.grant_role_permission(
            GrantRolePermissionCommand(
                role=Role.SUPPORT_STAFF,
                permission="fleet_device.devices.read",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(len(uow.recorded_events), 1)
        self.assertEqual(uow.recorded_events[0].event_type, "RolePermissionGranted")

    async def test_grant_is_idempotent(self) -> None:
        service = PermissionApplicationService(clock=FixedClock(_NOW))
        uow = FakeIamUow()
        command = GrantRolePermissionCommand(
            role=Role.SUPPORT_STAFF,
            permission="fleet_device.devices.read",
            actor=make_actor(),
        )
        await service.grant_role_permission(command, uow=uow)
        await service.grant_role_permission(command, uow=uow)
        permissions = await service.list_permissions_for_role(
            Role.SUPPORT_STAFF, uow=uow
        )
        self.assertEqual(len(permissions), 1)

    async def test_revoke_removes_the_granted_permission(self) -> None:
        service = PermissionApplicationService(clock=FixedClock(_NOW))
        uow = FakeIamUow()
        await service.grant_role_permission(
            GrantRolePermissionCommand(
                role=Role.SUPPORT_STAFF,
                permission="fleet_device.devices.read",
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.revoke_role_permission(
            RevokeRolePermissionCommand(
                role=Role.SUPPORT_STAFF,
                permission="fleet_device.devices.read",
                actor=make_actor(),
            ),
            uow=uow,
        )
        permissions = await service.list_permissions_for_role(
            Role.SUPPORT_STAFF, uow=uow
        )
        self.assertNotIn("fleet_device.devices.read", permissions)

    async def test_revoke_records_role_permission_revoked_event(self) -> None:
        service = PermissionApplicationService(clock=FixedClock(_NOW))
        uow = FakeIamUow()
        await service.revoke_role_permission(
            RevokeRolePermissionCommand(
                role=Role.SUPPORT_STAFF,
                permission="fleet_device.devices.read",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(uow.recorded_events[0].event_type, "RolePermissionRevoked")

    async def test_list_for_role_with_no_grants_is_empty(self) -> None:
        service = PermissionApplicationService(clock=FixedClock(_NOW))
        uow = FakeIamUow()
        permissions = await service.list_permissions_for_role(Role.PARENT, uow=uow)
        self.assertEqual(permissions, frozenset())

    async def test_grants_are_isolated_per_role(self) -> None:
        service = PermissionApplicationService(clock=FixedClock(_NOW))
        uow = FakeIamUow()
        await service.grant_role_permission(
            GrantRolePermissionCommand(
                role=Role.SUPPORT_STAFF,
                permission="fleet_device.devices.read",
                actor=make_actor(),
            ),
            uow=uow,
        )
        driver_permissions = await service.list_permissions_for_role(
            Role.DRIVER, uow=uow
        )
        self.assertEqual(driver_permissions, frozenset())


class FakeScopeAssignmentRepository:
    def __init__(self) -> None:
        self._regions: set[tuple[str, str]] = set()
        self._orgs: set[tuple[str, str]] = set()

    async def list_assigned_region_ids(self, user_id: str) -> frozenset[str]:
        return frozenset(r for u, r in self._regions if u == user_id)

    async def list_assigned_organization_ids(self, user_id: str) -> frozenset[str]:
        return frozenset(o for u, o in self._orgs if u == user_id)

    async def grant_region(self, user_id: str, region_id: str, *, granted_by) -> None:  # noqa: ANN001
        self._regions.add((user_id, region_id))

    async def revoke_region(self, user_id: str, region_id: str) -> None:
        self._regions.discard((user_id, region_id))

    async def grant_organization(
        self, user_id: str, organization_id: str, *, granted_by
    ) -> None:  # noqa: ANN001
        self._orgs.add((user_id, organization_id))

    async def revoke_organization(self, user_id: str, organization_id: str) -> None:
        self._orgs.discard((user_id, organization_id))


class FakeOrganizationUow:
    def __init__(self) -> None:
        self.scope_assignments = FakeScopeAssignmentRepository()
        self.recorded_events = []
        self.commit_count = 0

    def record_events(self, events) -> None:  # noqa: ANN001
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> "FakeOrganizationUow":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        pass


class ScopeAssignmentApplicationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_grant_region_then_list_round_trips(self) -> None:
        service = ScopeAssignmentApplicationService(clock=FixedClock(_NOW))
        uow = FakeOrganizationUow()
        await service.grant_region_assignment(
            GrantRegionAssignmentCommand(
                user_id="user-1", region_id="region-1", actor=make_actor()
            ),
            uow=uow,
        )
        region_ids = await service.list_region_assignments("user-1", uow=uow)
        self.assertIn("region-1", region_ids)
        self.assertEqual(uow.commit_count, 1)

    async def test_grant_region_records_event(self) -> None:
        service = ScopeAssignmentApplicationService(clock=FixedClock(_NOW))
        uow = FakeOrganizationUow()
        await service.grant_region_assignment(
            GrantRegionAssignmentCommand(
                user_id="user-1", region_id="region-1", actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(
            uow.recorded_events[0].event_type, "RegionAssignmentGranted"
        )

    async def test_revoke_region_removes_the_grant(self) -> None:
        service = ScopeAssignmentApplicationService(clock=FixedClock(_NOW))
        uow = FakeOrganizationUow()
        await service.grant_region_assignment(
            GrantRegionAssignmentCommand(
                user_id="user-1", region_id="region-1", actor=make_actor()
            ),
            uow=uow,
        )
        await service.revoke_region_assignment(
            RevokeRegionAssignmentCommand(
                user_id="user-1", region_id="region-1", actor=make_actor()
            ),
            uow=uow,
        )
        region_ids = await service.list_region_assignments("user-1", uow=uow)
        self.assertNotIn("region-1", region_ids)

    async def test_grant_support_then_list_round_trips(self) -> None:
        service = ScopeAssignmentApplicationService(clock=FixedClock(_NOW))
        uow = FakeOrganizationUow()
        await service.grant_support_assignment(
            GrantSupportAssignmentCommand(
                user_id="user-2", organization_id="org-1", actor=make_actor()
            ),
            uow=uow,
        )
        org_ids = await service.list_organization_assignments("user-2", uow=uow)
        self.assertIn("org-1", org_ids)

    async def test_revoke_support_removes_the_grant(self) -> None:
        service = ScopeAssignmentApplicationService(clock=FixedClock(_NOW))
        uow = FakeOrganizationUow()
        await service.grant_support_assignment(
            GrantSupportAssignmentCommand(
                user_id="user-2", organization_id="org-1", actor=make_actor()
            ),
            uow=uow,
        )
        await service.revoke_support_assignment(
            RevokeSupportAssignmentCommand(
                user_id="user-2", organization_id="org-1", actor=make_actor()
            ),
            uow=uow,
        )
        org_ids = await service.list_organization_assignments("user-2", uow=uow)
        self.assertNotIn("org-1", org_ids)

    async def test_region_and_support_assignments_are_independent(self) -> None:
        service = ScopeAssignmentApplicationService(clock=FixedClock(_NOW))
        uow = FakeOrganizationUow()
        await service.grant_region_assignment(
            GrantRegionAssignmentCommand(
                user_id="user-3", region_id="region-1", actor=make_actor()
            ),
            uow=uow,
        )
        region_ids = await service.list_region_assignments("user-3", uow=uow)
        org_ids = await service.list_organization_assignments("user-3", uow=uow)
        self.assertEqual(region_ids, frozenset({"region-1"}))
        self.assertEqual(org_ids, frozenset())


class CompositeKeyEventAggregateIdRegressionTests(unittest.TestCase):
    """Regression coverage for a real, live-caught production bug (Priority 1 Item 6): these
    six event factories previously built `aggregate_id` from a composite string
    (`f"{role}:{permission}"` or `f"{user_id}:{region_id}"`), which reliably exceeds
    `outbox.aggregate_id`/`audit_entries.entity_id`'s shared `CHAR(26)` column width — caught
    only once this item's new HTTP routes made these factories reachable for the first time,
    via `asyncpg.exceptions.StringDataRightTruncationError` against a real, live Postgres
    database (no in-memory fake or unit test could have caught this, since neither enforces a
    real column-width constraint). Fixed by passing `aggregate_id=None` instead — the full
    identifying data stays in `payload`. These tests lock that fix in place."""

    def test_role_permission_granted_has_no_aggregate_id(self) -> None:
        event = iam_events.role_permission_granted(
            role="SUPPORT_STAFF",
            permission="organization.scope_assignments.grant",
            occurred_at=_NOW,
            actor_id="actor-1",
        )
        self.assertIsNone(event.aggregate_id)
        self.assertEqual(event.payload["role"], "SUPPORT_STAFF")
        self.assertEqual(
            event.payload["permission"], "organization.scope_assignments.grant"
        )

    def test_role_permission_revoked_has_no_aggregate_id(self) -> None:
        event = iam_events.role_permission_revoked(
            role="SUPPORT_STAFF",
            permission="organization.scope_assignments.grant",
            occurred_at=_NOW,
            actor_id="actor-1",
        )
        self.assertIsNone(event.aggregate_id)

    def test_region_assignment_granted_has_no_aggregate_id(self) -> None:
        # Two real 26-char ULIDs plus a separator - the exact shape that overflowed CHAR(26)
        # live, even though ULIDs alone always fit.
        event = org_events.region_assignment_granted(
            user_id="01J8Z3K9G6X8YV5T4N2R7QW3MC",
            region_id="01J8Z3K9G6X8YV5T4N2R7QW3MD",
            occurred_at=_NOW,
            actor_id="actor-1",
        )
        self.assertIsNone(event.aggregate_id)
        self.assertEqual(event.payload["user_id"], "01J8Z3K9G6X8YV5T4N2R7QW3MC")

    def test_region_assignment_revoked_has_no_aggregate_id(self) -> None:
        event = org_events.region_assignment_revoked(
            user_id="01J8Z3K9G6X8YV5T4N2R7QW3MC",
            region_id="01J8Z3K9G6X8YV5T4N2R7QW3MD",
            occurred_at=_NOW,
            actor_id="actor-1",
        )
        self.assertIsNone(event.aggregate_id)

    def test_support_assignment_granted_has_no_aggregate_id(self) -> None:
        event = org_events.support_assignment_granted(
            user_id="01J8Z3K9G6X8YV5T4N2R7QW3MC",
            organization_id="01J8Z3K9G6X8YV5T4N2R7QW3ME",
            occurred_at=_NOW,
            actor_id="actor-1",
        )
        self.assertIsNone(event.aggregate_id)

    def test_support_assignment_revoked_has_no_aggregate_id(self) -> None:
        event = org_events.support_assignment_revoked(
            user_id="01J8Z3K9G6X8YV5T4N2R7QW3MC",
            organization_id="01J8Z3K9G6X8YV5T4N2R7QW3ME",
            occurred_at=_NOW,
            actor_id="actor-1",
        )
        self.assertIsNone(event.aggregate_id)


if __name__ == "__main__":
    unittest.main()
