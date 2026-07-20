"""SQLAlchemy repository implementation for `video` (Backend LLD §7, §8; Database Design §7.4).
Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query mechanics; every
ORM <-> domain conversion goes through `mappers.py`. Mirrors `billing.infra.repositories`'s
identity-map/`flush_tracked_changes` pattern exactly.

**`list_all`'s unrestricted-`TenantRegionScope` caveat carries over unchanged** — the same
system-wide gap every other module's `list_all` in this codebase already flags, not a
`video`-specific one.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.video.application.ports import VideoUnitOfWork
from raad.modules.video.domain.entities import VideoSession
from raad.modules.video.domain.repositories import VideoSessionRepository
from raad.modules.video.domain.value_objects import VideoSessionId
from raad.modules.video.infra.mappers import model_to_video_session, video_session_to_model
from raad.modules.video.infra.models import VideoSessionModel


class SqlAlchemyVideoSessionRepository(
    SqlAlchemyRepositoryBase[VideoSessionModel], VideoSessionRepository
):
    model = VideoSessionModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[VideoSession, VideoSessionModel]] = {}

    async def get(self, video_session_id: VideoSessionId) -> VideoSession | None:
        row = await self.get_by_id(str(video_session_id))
        return self._track(row)

    def add(self, video_session: VideoSession) -> None:
        model = video_session_to_model(video_session)
        super().add(model)
        self._tracked[str(video_session.id)] = (video_session, model)

    async def list_all(self) -> list[VideoSession]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_video_session(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for session, model in self._tracked.values():
            video_session_to_model(session, existing=model)

    def _track(self, row: VideoSessionModel | None) -> VideoSession | None:
        if row is None:
            return None
        session = model_to_video_session(row)
        self._tracked[row.id] = (session, row)
        return session


class SqlAlchemyVideoUnitOfWork(SqlAlchemyUnitOfWork, VideoUnitOfWork):
    """Concrete `VideoUnitOfWork` (Backend LLD §8.2/§6.2). Identical shape to
    `billing.infra.repositories.SqlAlchemyBillingUnitOfWork`.
    """

    video_sessions: SqlAlchemyVideoSessionRepository

    async def __aenter__(self) -> "SqlAlchemyVideoUnitOfWork":
        await super().__aenter__()
        self.video_sessions = SqlAlchemyVideoSessionRepository(self.session)
        return self

    async def commit(self) -> None:
        self.video_sessions.flush_tracked_changes()
        await super().commit()
