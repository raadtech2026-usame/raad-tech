"""Idempotency foundation (Backend LLD §10.3/§11.3: "consumers are idempotent (dedupe on
`event_id`) so at-least-once delivery is safe"). `InMemoryIdempotencyStore` is a
process-local, non-durable placeholder — safe for single-process dev/test only. It is **not**
safe across multiple worker processes or restarts (state is lost, and two processes don't
share it); replace with a Redis- or DB-backed store before running more than one worker
process. Redis isn't an approved dependency for this phase (per this phase's scope), and a
durable store would need a new business-adjacent table, so neither is implemented here.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod


class IdempotencyStore(ABC):
    @abstractmethod
    async def has_processed(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def mark_processed(self, key: str) -> None:
        raise NotImplementedError


class InMemoryIdempotencyStore(IdempotencyStore):
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = asyncio.Lock()

    async def has_processed(self, key: str) -> bool:
        async with self._lock:
            return key in self._seen

    async def mark_processed(self, key: str) -> None:
        async with self._lock:
            self._seen.add(key)
