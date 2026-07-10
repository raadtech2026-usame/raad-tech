"""ID generation port (Backend LLD §17 `ids`; open item §20.2).

The concrete strategy (UUIDv7 vs ULID — both time-sortable, index-friendly) is an explicit
open item in the Backend LLD, not yet decided. Only the port is defined here; no concrete
generator is bound in `core/di` until the decision is made, so nothing silently commits to a
default.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class IdGenerator(ABC):
    @abstractmethod
    def new_id(self) -> str:
        raise NotImplementedError
