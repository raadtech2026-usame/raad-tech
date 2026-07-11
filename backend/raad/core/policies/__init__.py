"""Base policy abstractions (Backend LLD §17 `policies`) — the home for concrete,
access-critical decision objects such as `SubscriptionAccessPolicy` (CR-1) and
`VideoAccessPolicy` (D5), added once their owning modules (`billing`, `video`) exist.

Only the generic `Policy`/`PolicyDecision` shape is defined in this phase: an encapsulated
decision object returning `allowed` plus an optional `reason`/`required_action` the API can
surface to the caller (e.g. so a Flutter app can route a denied parent to a payment screen).
No concrete policy — inventing `SubscriptionAccessPolicy` or `VideoAccessPolicy` logic here
would be business logic ahead of their owning modules, which this phase is scoped to avoid.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None
    required_action: str | None = None


class Policy(ABC):
    """Marker base for encapsulated decision objects (§5.3). Concrete policies define their
    own `evaluate(...)` signature (the inputs a decision depends on differ per policy), so no
    abstract method is declared here beyond the shared `PolicyDecision` return shape."""

    @abstractmethod
    def evaluate(self, *args: object, **kwargs: object) -> PolicyDecision:
        raise NotImplementedError


__all__ = ["Policy", "PolicyDecision"]
