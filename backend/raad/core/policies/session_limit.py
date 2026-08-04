"""`SessionLimitPolicy` — ADR-0019 (Account-Sharing Protection, concurrent session cap).
Mirrors `subscription_access.SubscriptionAccessPolicy`'s shape exactly: a pure, I/O-free
decision object over primitives resolved by the caller before `evaluate()` is invoked
(`.claude/rules/testing.md` #3: security-relevant invariants get an explicit regression test,
not incidental coverage).

**Scope, deliberately narrow.** This policy only answers "is the caller over the configured
cap?" — it does not decide *which* sessions to evict or perform the eviction itself. ADR-0019
Decision #2 ("revoke the oldest... until back under the cap") is a deterministic mechanical
action over data the policy is never given (each session's `issued_at`), so it stays in the
enforcement point (`iam.application.services.AuthApplicationService.login`/`refresh`), the same
division of labor `SubscriptionAccessPolicy`'s own module docstring documents: "Inputs (all
resolved before the policy is called; the policy itself is pure)."
"""

from __future__ import annotations

from raad.core.policies.base import Policy, PolicyDecision

_REASON_SESSION_CAP_EXCEEDED = "SESSION_CAP_EXCEEDED"


class SessionLimitPolicy(Policy):
    """ADR-0019. `active_session_count` is expected to already include the session about to be
    issued (the caller's responsibility — see the enforcement point's own docstring)."""

    def evaluate(
        self, *, active_session_count: int, max_sessions: int
    ) -> PolicyDecision:
        if active_session_count <= max_sessions:
            return PolicyDecision(allowed=True)
        return PolicyDecision(allowed=False, reason=_REASON_SESSION_CAP_EXCEEDED)


__all__ = ["SessionLimitPolicy"]
