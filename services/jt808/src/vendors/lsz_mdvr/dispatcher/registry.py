"""Handler registry keyed by command keyword (e.g. `"V101"`) — the vendor-protocol equivalent of
`src.dispatcher.registry.HandlerRegistry`."""

from __future__ import annotations

from src.vendors.lsz_mdvr.dispatcher.handler import MdvrMessageHandler


class DuplicateMdvrHandlerError(Exception):
    """A handler is already registered for a given keyword."""


class MdvrHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, MdvrMessageHandler] = {}

    def register(self, keyword: str, handler: MdvrMessageHandler) -> None:
        if keyword in self._handlers:
            raise DuplicateMdvrHandlerError(
                f"A handler is already registered for keyword {keyword!r}."
            )
        self._handlers[keyword] = handler

    def resolve(self, keyword: str) -> MdvrMessageHandler | None:
        return self._handlers.get(keyword)

    def __len__(self) -> int:
        return len(self._handlers)
