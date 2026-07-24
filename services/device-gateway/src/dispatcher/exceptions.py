"""Dispatcher error hierarchy (Phase 9.4). A handler raising an exception during `handle()`
never crashes the connection (`dispatcher.py`'s `dispatch()` catches broadly and logs) — these
typed errors are for dispatcher-owned failures, distinct from that catch-all.
"""

from __future__ import annotations


class DispatcherError(Exception):
    """Base for all Phase 9.4 dispatcher errors."""


class DuplicateHandlerError(DispatcherError):
    """Raised by `HandlerRegistry.register` when a handler is already registered for a given
    `message_id`. No handler-replacement semantics are documented anywhere in the approved
    JT808 Technical Design or the primary spec, so registration is one-shot — replacing a
    handler requires a new `HandlerRegistry`, not a `replace()` method this phase invents.
    """
