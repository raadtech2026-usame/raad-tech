"""Unit tests for `core.policies.video_access.VideoAccessPolicy` (Phase 14, D5). Stdlib
`unittest` — no `pytest`. Exhaustively covers every role from API Contracts §3.2's "Live video /
playback" capability row (Founder/Regional Manager/Support/Finance/Org Admin/Driver/Parent), not
just Parent — D5 is a hard security invariant ("Parent has zero reachable path to video,
anywhere, ever") but the exclusion of Finance/Driver is equally load-bearing and equally
regression-worthy (`.claude/rules/testing.md` #3).
"""

from __future__ import annotations

import unittest

from raad.core.policies.base import Policy
from raad.core.policies.video_access import VideoAccessPolicy
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope

ORG_A = "01J8Z3K9G6X8YV5T4N2R7QW3MA"
ORG_B = "01J8Z3K9G6X8YV5T4N2R7QW3MB"


def make_principal(role: Role, org_id: str | None = ORG_A) -> Principal:
    return Principal(user_id="user-1", role=role, org_id=org_id)


class VideoAccessPolicyIsAPolicyTests(unittest.TestCase):
    def test_extends_the_shared_policy_base(self) -> None:
        self.assertIsInstance(VideoAccessPolicy(), Policy)


class NeverEligibleRolesTests(unittest.TestCase):
    """API Contracts §3.2: Parent and Driver are '❌' regardless of org/scope - D5's 'no
    reachable path' invariant, and Finance Staff's '❌' in the same row (excluded even though
    a RAAD-staff role) - proven even with an unrestricted org_scope, so a permissive scope
    can never compensate for an ineligible role."""

    def setUp(self) -> None:
        self.policy = VideoAccessPolicy()
        self.unrestricted_scope = TenantRegionScope(organization_ids=None)

    def test_parent_is_denied_even_with_unrestricted_scope(self) -> None:
        decision = self.policy.evaluate(
            principal=make_principal(Role.PARENT),
            device_organization_id=ORG_A,
            org_scope=self.unrestricted_scope,
        )
        self.assertFalse(decision.allowed)

    def test_driver_is_denied_even_with_unrestricted_scope(self) -> None:
        decision = self.policy.evaluate(
            principal=make_principal(Role.DRIVER),
            device_organization_id=ORG_A,
            org_scope=self.unrestricted_scope,
        )
        self.assertFalse(decision.allowed)

    def test_finance_staff_is_denied_even_with_unrestricted_scope(self) -> None:
        """The one non-obvious exclusion: Finance is RAAD staff but explicitly '❌' in the
        documented capability matrix, unlike Founder/Regional Manager/Support."""
        decision = self.policy.evaluate(
            principal=make_principal(Role.FINANCE_STAFF, org_id=None),
            device_organization_id=ORG_A,
            org_scope=self.unrestricted_scope,
        )
        self.assertFalse(decision.allowed)

    def test_ineligible_roles_never_carry_a_reason_or_action(self) -> None:
        """D5 documents no reason/required_action taxonomy for video (unlike CR-1)."""
        decision = self.policy.evaluate(
            principal=make_principal(Role.PARENT),
            device_organization_id=ORG_A,
            org_scope=self.unrestricted_scope,
        )
        self.assertIsNone(decision.reason)
        self.assertIsNone(decision.required_action)


class OrgAdminOwnOrgTests(unittest.TestCase):
    """API Contracts §3.2: Org Admin '✅ own org'."""

    def setUp(self) -> None:
        self.policy = VideoAccessPolicy()

    def test_org_admin_within_own_org_is_granted(self) -> None:
        scope = TenantRegionScope(organization_ids=frozenset({ORG_A}))
        decision = self.policy.evaluate(
            principal=make_principal(Role.ORG_ADMIN, org_id=ORG_A),
            device_organization_id=ORG_A,
            org_scope=scope,
        )
        self.assertTrue(decision.allowed)

    def test_org_admin_outside_own_org_is_denied(self) -> None:
        """A device belonging to a different org than the Org Admin's own scope allows."""
        scope = TenantRegionScope(organization_ids=frozenset({ORG_A}))
        decision = self.policy.evaluate(
            principal=make_principal(Role.ORG_ADMIN, org_id=ORG_A),
            device_organization_id=ORG_B,
            org_scope=scope,
        )
        self.assertFalse(decision.allowed)


class RaadStaffScopeTests(unittest.TestCase):
    """API Contracts §3.2: Founder '✅*', Regional Manager/Support '✅*(permitted)' - all three
    gated by org_scope once resolved (Founder unrestricted; Regional Manager/Support their
    assigned regions/orgs, per `core.tenancy.resolver.ScopeResolver`'s documented formula)."""

    def setUp(self) -> None:
        self.policy = VideoAccessPolicy()

    def test_founder_with_unrestricted_scope_is_granted_for_any_org(self) -> None:
        scope = TenantRegionScope(organization_ids=None)
        decision = self.policy.evaluate(
            principal=make_principal(Role.FOUNDER, org_id=None),
            device_organization_id=ORG_B,
            org_scope=scope,
        )
        self.assertTrue(decision.allowed)

    def test_regional_manager_within_assigned_scope_is_granted(self) -> None:
        scope = TenantRegionScope(organization_ids=frozenset({ORG_A, ORG_B}))
        decision = self.policy.evaluate(
            principal=make_principal(Role.REGIONAL_MANAGER, org_id=None),
            device_organization_id=ORG_B,
            org_scope=scope,
        )
        self.assertTrue(decision.allowed)

    def test_regional_manager_outside_assigned_scope_is_denied(self) -> None:
        scope = TenantRegionScope(organization_ids=frozenset({ORG_A}))
        decision = self.policy.evaluate(
            principal=make_principal(Role.REGIONAL_MANAGER, org_id=None),
            device_organization_id=ORG_B,
            org_scope=scope,
        )
        self.assertFalse(decision.allowed)

    def test_support_staff_within_assigned_scope_is_granted(self) -> None:
        scope = TenantRegionScope(organization_ids=frozenset({ORG_A}))
        decision = self.policy.evaluate(
            principal=make_principal(Role.SUPPORT_STAFF, org_id=None),
            device_organization_id=ORG_A,
            org_scope=scope,
        )
        self.assertTrue(decision.allowed)

    def test_support_staff_outside_assigned_scope_is_denied(self) -> None:
        scope = TenantRegionScope(organization_ids=frozenset())
        decision = self.policy.evaluate(
            principal=make_principal(Role.SUPPORT_STAFF, org_id=None),
            device_organization_id=ORG_A,
            org_scope=scope,
        )
        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
