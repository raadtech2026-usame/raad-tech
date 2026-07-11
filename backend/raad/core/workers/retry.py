"""Retry strategy foundation (Backend LLD §11.3: "Retry with backoff, bounded attempts, then
dead-letter queue + alert"). `ExponentialBackoffRetryPolicy` is pure arithmetic (no I/O, no
broker dependency) so it's safe to implement concretely now, independent of which broker/
worker runtime is eventually chosen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class RetryPolicy(ABC):
    @abstractmethod
    def next_delay(self, attempt: int) -> float | None:
        """Delay in seconds before the next attempt (1-indexed `attempt` = the attempt that
        just failed). Returns `None` when attempts are exhausted — the caller should route the
        failed unit of work to the Dead Letter Queue (`core.workers.dlq.DeadLetterQueue`).
        """
        raise NotImplementedError


class ExponentialBackoffRetryPolicy(RetryPolicy):
    def __init__(
        self, *, max_attempts: int, base_delay_seconds: float, max_delay_seconds: float
    ) -> None:
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds

    def next_delay(self, attempt: int) -> float | None:
        if attempt >= self._max_attempts:
            return None
        return min(self._base_delay_seconds * (2 ** (attempt - 1)), self._max_delay_seconds)
