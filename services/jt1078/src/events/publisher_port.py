"""`SessionEventPublisher` — the port `session/session_manager.py` uses to publish lifecycle
facts and stop-signal commands, mirroring `device-gateway`'s own `EventPublisher` port shape
(a deliberate, independent mirror — no shared code between deployables,
`.claude/rules/architecture.md` #2). `LoggingSessionEventPublisher` is the default until a real
broker is configured — degrades to a structured log line, never a crash, matching every other
not-yet-bound-broker default in this codebase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Union

from src.events.session_events import VideoSessionActivated, VideoSessionEnded, VideoSessionFailed
from src.logging_setup import get_logger, log_with_fields

logger = get_logger("jt1078_relay.events.publisher")

SessionEvent = Union[VideoSessionActivated, VideoSessionEnded, VideoSessionFailed]


class SessionEventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: SessionEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    async def publish_stop_command(
        self,
        *,
        terminal_id: str,
        correlation_id: str,
        command: str,
        fields: dict[str, object],
    ) -> None:
        """Publishes a `Jt1078SignalCommandRequested` event, the same wire contract
        `device-gateway`'s `RedisVideoSignalingConsumer` already consumes from the Business API
        (ADR-0024 §5 point 4 — the relay is a second legitimate publisher of this event family,
        for teardown only)."""
        raise NotImplementedError


class LoggingSessionEventPublisher(SessionEventPublisher):
    async def publish(self, event: SessionEvent) -> None:
        log_with_fields(
            logger,
            20,
            "session_event",
            event_type=type(event).__name__,
            session_id=event.session_id,
            terminal_id=event.terminal_id,
            correlation_id=event.correlation_id,
        )

    async def publish_stop_command(
        self,
        *,
        terminal_id: str,
        correlation_id: str,
        command: str,
        fields: dict[str, object],
    ) -> None:
        log_with_fields(
            logger,
            20,
            "stop_command_requested",
            terminal_id=terminal_id,
            correlation_id=correlation_id,
            command=command,
        )
