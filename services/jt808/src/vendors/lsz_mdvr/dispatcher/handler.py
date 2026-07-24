"""`MdvrMessageHandler`/`MdvrHandlerContext`/`MdvrHandlerResult` — the vendor-protocol equivalent
of `src.dispatcher.handler`'s trio, keyed by string `keyword` instead of an integer `message_id`
(this protocol has no numeric message identity, `docs/vendor/HARDWARE_ANALYSIS.md` §2). Same
division of responsibility: handlers validate/update session/hand off to the event publisher;
the dispatcher owns response encoding and connection close timing.

`MdvrHandlerContext` carries exactly what a handler may depend on: the connection id and the
*reused, unmodified* `DeviceSessionManager` from the parent package (`src.session.
device_session_manager`) — no SQLAlchemy/FastAPI/business-module access reachable from here,
matching the parent package's own architecture boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.vendors.lsz_mdvr.protocol.message import MdvrInboundMessage

if TYPE_CHECKING:
    from src.session.device_session_manager import DeviceSessionManager


@dataclass(frozen=True)
class MdvrHandlerContext:
    connection_id: str
    device_sessions: "DeviceSessionManager"


@dataclass(frozen=True)
class MdvrHandlerResult:
    response_keyword: str | None = None
    response_fields: list[str] | None = None
    close_connection_after: bool = False
    close_reason: str | None = None

    @classmethod
    def no_response(cls) -> "MdvrHandlerResult":
        return cls()


class MdvrMessageHandler(ABC):
    @abstractmethod
    async def handle(
        self, message: MdvrInboundMessage, context: MdvrHandlerContext
    ) -> MdvrHandlerResult:
        raise NotImplementedError
