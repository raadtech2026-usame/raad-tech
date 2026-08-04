"""Unit tests for `core.policies.session_limit.SessionLimitPolicy` (ADR-0019, account-sharing
concurrent session cap). Stdlib `unittest` — no `pytest`, matching every other test file in this
codebase. Exhaustively covers boundary cases (exactly at cap, one over, cap of 1) — a safety/
access-control policy (`.claude/rules/testing.md` #3).
"""

from __future__ import annotations

import unittest

from raad.core.policies.base import Policy, PolicyDecision
from raad.core.policies.session_limit import SessionLimitPolicy


class SessionLimitPolicyIsAPolicyTests(unittest.TestCase):
    def test_extends_the_shared_policy_base(self) -> None:
        self.assertIsInstance(SessionLimitPolicy(), Policy)


class SessionLimitPolicyBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = SessionLimitPolicy()

    def test_count_below_cap_is_allowed(self) -> None:
        decision = self.policy.evaluate(active_session_count=2, max_sessions=5)
        self.assertTrue(decision.allowed)
        self.assertIsNone(decision.reason)

    def test_count_exactly_at_cap_is_allowed(self) -> None:
        decision = self.policy.evaluate(active_session_count=5, max_sessions=5)
        self.assertTrue(decision.allowed)

    def test_count_one_over_cap_is_denied(self) -> None:
        decision = self.policy.evaluate(active_session_count=6, max_sessions=5)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SESSION_CAP_EXCEEDED")

    def test_count_far_over_cap_is_denied(self) -> None:
        decision = self.policy.evaluate(active_session_count=50, max_sessions=5)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SESSION_CAP_EXCEEDED")

    def test_cap_of_one_allows_exactly_one_session(self) -> None:
        self.assertTrue(
            self.policy.evaluate(active_session_count=1, max_sessions=1).allowed
        )
        self.assertFalse(
            self.policy.evaluate(active_session_count=2, max_sessions=1).allowed
        )

    def test_denied_decision_never_carries_a_required_action(self) -> None:
        """Unlike `SubscriptionAccessPolicy`'s `REDIRECT_TO_PAYMENT`, a session-cap denial has
        no corresponding remedial action for the caller to take (the enforcement point itself
        resolves it by evicting the oldest session, not by asking the user to do something)."""
        decision = self.policy.evaluate(active_session_count=6, max_sessions=5)
        self.assertIsNone(decision.required_action)


class SessionLimitPolicyPurityTests(unittest.TestCase):
    def test_same_instance_is_stateless_across_calls(self) -> None:
        policy = SessionLimitPolicy()
        first = policy.evaluate(active_session_count=1, max_sessions=5)
        second = policy.evaluate(active_session_count=10, max_sessions=5)
        third = policy.evaluate(active_session_count=1, max_sessions=5)
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
