"""Outbound ports the `video` application layer depends on (Backend LLD §4.2). `UnitOfWork` is
the existing core abstraction (`core.db.unit_of_work`), extended here with `video`'s own
repository, mirroring `billing.application.ports.BillingUnitOfWork` exactly.

**`VideoProviderPort` — this phase's explicit MVP abstraction.** The user's own task scope for
this phase is unambiguous: "Do NOT implement native JT1078. For MVP the system will use the
hardware/vendor video API. Design the system around a `VideoProviderPort` abstraction. Implement
only the abstraction layer if needed. Native JT1078 implementation is intentionally postponed."
This port is that abstraction — it names the three capabilities the documented routes need
(start a live stream, start a playback stream, stop a stream) without committing to *which*
vendor/hardware API answers them, the same "domain never sees a provider-specific field"
Anti-Corruption-Layer posture `billing.application.ports.PaymentProviderPort`'s own docstring
already establishes for EVC Plus. No concrete implementation of this port exists this phase —
see `infra/adapters.py`'s own docstring for why.

`start_live`/`start_playback` return the provider's own stream URL/token — surfaced directly in
the API response (never persisted; `domain/entities.py`'s module docstring explains why
`VideoSession` itself carries no such column). `stop` returns nothing; a provider-side teardown
is fire-and-forget from this layer's perspective, mirroring `.claude/rules/jt1078.md` #4's "ports
are pooled and reclaimed on teardown" being the *provider's* responsibility, not this port
caller's.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.video.domain.repositories import VideoSessionRepository


class VideoProviderPort(ABC):
    """MVP hardware/vendor video API abstraction (see module docstring) — deliberately not
    JT1078-shaped; a concrete adapter for whichever vendor API is chosen implements this without
    this codebase's application/domain layers ever changing."""

    @abstractmethod
    async def start_live(self, *, device_id: str, camera_id: str, reference: str) -> str:
        """Requests a live stream from the vendor/hardware API; returns a stream URL/token."""
        raise NotImplementedError

    @abstractmethod
    async def start_playback(
        self,
        *,
        device_id: str,
        camera_id: str,
        window_start: datetime,
        window_end: datetime,
        reference: str,
    ) -> str:
        """Requests a playback stream for the given window; returns a stream URL/token."""
        raise NotImplementedError

    @abstractmethod
    async def stop(self, *, reference: str) -> None:
        """Tears down a previously started stream."""
        raise NotImplementedError


class VideoUnitOfWork(UnitOfWork):
    """Bundles this module's one repository onto one transaction boundary, mirroring
    `BillingUnitOfWork`'s identical shape. The concrete implementation is
    `infra.repositories.SqlAlchemyVideoUnitOfWork`.
    """

    video_sessions: VideoSessionRepository
