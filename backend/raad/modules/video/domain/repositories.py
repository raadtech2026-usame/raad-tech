"""Repository interface for the `video` module (Backend LLD §5.1/§7.1/§7.2). Framework-free —
no SQLAlchemy/FastAPI/Pydantic. No LLD contract skeleton exists for `VideoSessionRepository`
(unlike `TripRepository`) — mirrors the minimal `get`/`add`/`list_all` shape every other
no-module-owned-uniqueness-constraint aggregate in this codebase already uses (e.g.
`billing.domain.repositories.PlanRepository`). `video_sessions` (Database Design §7.4) declares
no unique constraint of its own beyond its primary key, so no dedicated finder is added.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.modules.video.domain.entities import VideoSession
from raad.modules.video.domain.value_objects import VideoSessionId


class VideoSessionRepository(ABC):
    @abstractmethod
    async def get(self, video_session_id: VideoSessionId) -> VideoSession | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, video_session: VideoSession) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[VideoSession]:
        """No documented `GET /video/sessions` list route exists (API Contracts §4.5 names only
        the three POST routes) — implemented anyway for the same reason `TransportFeeRepository.
        list_all` is: a complete, tested use-case at the layers below the router, not itself an
        HTTP-exposed capability."""
        raise NotImplementedError
