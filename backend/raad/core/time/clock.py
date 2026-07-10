"""Clock port (Backend LLD §17 `time`) — injectable time for deterministic domain tests."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        raise NotImplementedError


class SystemClock(Clock):
    """The real clock, bound in `core/di` for production use (§9.2)."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
