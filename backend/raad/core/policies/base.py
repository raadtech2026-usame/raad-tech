"""Base policy abstractions (Backend LLD §17 `policies`) — the shared shape every concrete,
access-critical decision object in this package builds on: `SubscriptionAccessPolicy` (CR-1,
`subscription_access.py`) and `VideoAccessPolicy` (D5, `video_access.py`).

Moved out of `__init__.py` into its own file in Phase 14, matching the established convention
every other `core/` package already follows (`core/errors/__init__.py` and
`core/tenancy/__init__.py` are both thin re-export hubs over sibling files, never holding logic
themselves) — `__init__.py` previously held this content directly, before either concrete
policy existed to import it.
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
