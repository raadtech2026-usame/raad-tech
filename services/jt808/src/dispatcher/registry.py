"""Handler registry keyed by `message_id` (Phase 9.4). "Message handlers must be independently
pluggable" — this registry is the plug point: each handler is registered once, against exactly
the `message_id`s JT808 Technical Design §7's dispatch flowchart and §8's table name
(`server.py`'s composition root does the actual registration).
"""

from __future__ import annotations

from src.dispatcher.exceptions import DuplicateHandlerError
from src.dispatcher.handler import MessageHandler


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[int, MessageHandler] = {}

    def register(self, message_id: int, handler: MessageHandler) -> None:
        if message_id in self._handlers:
            raise DuplicateHandlerError(
                f"A handler is already registered for message_id 0x{message_id:04x}."
            )
        self._handlers[message_id] = handler

    def resolve(self, message_id: int) -> MessageHandler | None:
        return self._handlers.get(message_id)

    def __len__(self) -> int:
        return len(self._handlers)
