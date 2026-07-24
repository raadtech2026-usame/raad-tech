"""`MessageHandler` interface, `HandlerContext`, `HandlerResult` (Phase 9.4; JT808 Technical
Design §7/§8). One handler per `message_id`; handlers are "thin" per §8's own description:
"validate, update session, and hand off to the event publisher — they do no business
persistence." This phase's handlers (`placeholder_handler.py`, `unknown_handler.py`) do even
less — no validation, no session mutation, no event publishing — since the real business
behavior for every named message (register/auth/heartbeat/location/alarm/etc.) belongs to a
later phase (§8 Handlers proper).

`HandlerContext` carries exactly what the architecture requirements allow a handler to depend
on: the owning connection's id and the session layer (`DeviceSessionManager`, Phase 9.2) — no
SQLAlchemy, FastAPI, Redis, or business-module (Tracking/Fleet Device/Organization) access is
reachable from here, by construction (nothing on this object exposes any of them).

`HandlerResult` is how a handler asks the dispatcher to send a response — the "Request ->
Response dispatch flow" the dispatcher owns (`dispatcher.py`). Per the resolved Phase 9.4
scope: `HandlerResult.no_response()` (both fields `None`) sends nothing; a handler that wants
a reply sets both `response_message_id` and `response_body`. `response_body` is a fully
formed, message-specific body — Phase 9.4's own handlers never construct one themselves (that
requires business content), only `UnknownMessageHandler` does (a generic "not supported" ack,
`general_response.py`); Phase 9.5's registration/authentication handlers are the first to
build real message-specific bodies (`handlers/registration_response.py`,
`dispatcher/general_response.py`).

**`close_connection_after`/`close_reason` (Phase 9.5 addition):** JT808 Technical Design §4 is
explicit that both a rejected registration and a failed authentication end with "reject +
audit + close" — the socket is closed *after* the rejection/failure response is sent. Declaring
this via `HandlerResult` (rather than a handler calling some close capability directly) keeps
"handlers own protocol behaviour only, dispatcher owns routing/flow" intact: the dispatcher
(`dispatcher.py`) sends the response first, then closes, in that order, using its own injected
`close_connection` callback — a handler never touches a `Connection`/`ConnectionManager`
object directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.protocol.message import InboundMessage

if TYPE_CHECKING:
    from src.session.device_session_manager import DeviceSessionManager


@dataclass(frozen=True)
class HandlerContext:
    connection_id: str
    device_sessions: "DeviceSessionManager"


@dataclass(frozen=True)
class HandlerResult:
    response_message_id: int | None = None
    response_body: bytes | None = None
    close_connection_after: bool = False
    close_reason: str | None = None

    @classmethod
    def no_response(cls) -> "HandlerResult":
        return cls()


class MessageHandler(ABC):
    @abstractmethod
    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        raise NotImplementedError
