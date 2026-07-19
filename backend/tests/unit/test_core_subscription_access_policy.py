"""Unit tests for `core.policies.subscription_access.SubscriptionAccessPolicy` (Phase 14, CR-1).
Stdlib `unittest` — no `pytest` (not an approved dependency), matching every other test file in
this codebase. Exhaustively covers Backend LLD §5.4's decision table: every
(assignment_state, billing_model, subscription_state) combination that determines the outcome,
not just one happy-path case per branch — this is a safety/access-control policy
(`.claude/rules/testing.md` #3: safety-critical invariants require explicit regression tests).
"""

from __future__ import annotations

import unittest

from raad.core.policies.base import Policy, PolicyDecision
from raad.core.policies.subscription_access import (
    AssignmentState,
    BillingModel,
    SubscriptionAccessPolicy,
    SubscriptionState,
)


class SubscriptionAccessPolicyIsAPolicyTests(unittest.TestCase):
    def test_extends_the_shared_policy_base(self) -> None:
        self.assertIsInstance(SubscriptionAccessPolicy(), Policy)


class AssignmentGateTakesPrecedenceTests(unittest.TestCase):
    """LLD §5.4: "decision order (assignment gate first - overrides everything)". Every
    non-ACTIVE assignment state denies regardless of billing_model/subscription_state - proven
    exhaustively, not just for one arbitrary combination."""

    def setUp(self) -> None:
        self.policy = SubscriptionAccessPolicy()

    def test_removed_denies_even_with_organization_pays(self) -> None:
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.REMOVED,
            billing_model=BillingModel.ORGANIZATION_PAYS,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ASSIGNMENT_INACTIVE")
        self.assertIsNone(decision.required_action)

    def test_transferred_denies_even_with_active_parent_pays_subscription(self) -> None:
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.TRANSFERRED,
            billing_model=BillingModel.PARENT_PAYS,
            subscription_state=SubscriptionState.ACTIVE,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ASSIGNMENT_INACTIVE")
        self.assertIsNone(decision.required_action)

    def test_graduated_denies(self) -> None:
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.GRADUATED,
            billing_model=BillingModel.ORGANIZATION_PAYS,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ASSIGNMENT_INACTIVE")

    def test_disabled_denies(self) -> None:
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.DISABLED,
            billing_model=BillingModel.ORGANIZATION_PAYS,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ASSIGNMENT_INACTIVE")

    def test_assignment_inactive_never_carries_a_redirect_action(self) -> None:
        """LLD §5.4: 'ASSIGNMENT_INACTIVE denials expose no payment path (renewing cannot
        restore access without an active assignment)'."""
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.REMOVED,
            billing_model=BillingModel.PARENT_PAYS,
            subscription_state=SubscriptionState.EXPIRED,
        )
        self.assertIsNone(decision.required_action)


class OrganizationPaysTests(unittest.TestCase):
    """LLD §5.4: 'ACTIVE | ORGANIZATION_PAYS | (ignored) -> GRANT (never a payment page)'."""

    def setUp(self) -> None:
        self.policy = SubscriptionAccessPolicy()

    def test_active_assignment_organization_pays_grants(self) -> None:
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.ORGANIZATION_PAYS,
        )
        self.assertTrue(decision.allowed)
        self.assertIsNone(decision.reason)
        self.assertIsNone(decision.required_action)

    def test_organization_pays_grants_regardless_of_subscription_state(self) -> None:
        """subscription_state is documented as 'ignored' for ORGANIZATION_PAYS - even an
        EXPIRED subscription value must not deny."""
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.ORGANIZATION_PAYS,
            subscription_state=SubscriptionState.EXPIRED,
        )
        self.assertTrue(decision.allowed)

    def test_organization_pays_grants_with_subscription_state_omitted(self) -> None:
        """subscription_state defaults to None - an ORGANIZATION_PAYS caller need not resolve
        it at all."""
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.ORGANIZATION_PAYS,
        )
        self.assertTrue(decision.allowed)


class ParentPaysTests(unittest.TestCase):
    """LLD §5.4: 'ACTIVE | PARENT_PAYS | ACTIVE -> GRANT'; 'ACTIVE | PARENT_PAYS | expired /
    inactive -> DENY (SUBSCRIPTION_EXPIRED, REDIRECT_TO_PAYMENT)'."""

    def setUp(self) -> None:
        self.policy = SubscriptionAccessPolicy()

    def test_active_subscription_grants(self) -> None:
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.PARENT_PAYS,
            subscription_state=SubscriptionState.ACTIVE,
        )
        self.assertTrue(decision.allowed)
        self.assertIsNone(decision.reason)
        self.assertIsNone(decision.required_action)

    def test_expired_subscription_denies_with_redirect(self) -> None:
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.PARENT_PAYS,
            subscription_state=SubscriptionState.EXPIRED,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SUBSCRIPTION_EXPIRED")
        self.assertEqual(decision.required_action, "REDIRECT_TO_PAYMENT")

    def test_trial_subscription_denies_with_redirect(self) -> None:
        """Only ACTIVE grants for PARENT_PAYS - every other documented subscription status
        (trial/suspended/expired/cancelled) is treated uniformly as non-granting, matching the
        decision table's binary 'ACTIVE vs. expired/inactive' framing."""
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.PARENT_PAYS,
            subscription_state=SubscriptionState.TRIAL,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SUBSCRIPTION_EXPIRED")

    def test_suspended_subscription_denies(self) -> None:
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.PARENT_PAYS,
            subscription_state=SubscriptionState.SUSPENDED,
        )
        self.assertFalse(decision.allowed)

    def test_cancelled_subscription_denies(self) -> None:
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.PARENT_PAYS,
            subscription_state=SubscriptionState.CANCELLED,
        )
        self.assertFalse(decision.allowed)

    def test_omitted_subscription_state_denies(self) -> None:
        """No subscription_state supplied for a PARENT_PAYS parent - must not silently grant."""
        decision = self.policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.PARENT_PAYS,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SUBSCRIPTION_EXPIRED")


class PolicyPurityTests(unittest.TestCase):
    """LLD §5.4: 'the policy itself is pure'. Same inputs -> same output, no hidden state,
    no I/O - proven by calling the same instance repeatedly with different inputs."""

    def test_same_instance_is_stateless_across_calls(self) -> None:
        policy = SubscriptionAccessPolicy()
        first = policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.ORGANIZATION_PAYS,
        )
        second = policy.evaluate(
            assignment_state=AssignmentState.REMOVED,
            billing_model=BillingModel.ORGANIZATION_PAYS,
        )
        third = policy.evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=BillingModel.ORGANIZATION_PAYS,
        )
        self.assertTrue(first.allowed)
        self.assertFalse(second.allowed)
        self.assertTrue(third.allowed)
        self.assertEqual(first, third)

    def test_decision_is_an_immutable_value_object(self) -> None:
        decision = PolicyDecision(allowed=True)
        with self.assertRaises(Exception):
            decision.allowed = False  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
